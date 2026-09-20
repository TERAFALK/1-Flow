import io
import math
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from ..database import get_db
from ..deps import get_current_user
from ..schemas import VehicleCreate, VehicleUpdate, VehicleOut
from ..pdf_utils import draw_header, draw_info_panel, draw_paragraph
from .. import models
from .. import turning
from .. import axleload

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def _load_vehicle(db: Session, vehicle_id: int) -> models.Vehicle:
    vehicle = (
        db.query(models.Vehicle)
        .options(joinedload(models.Vehicle.customer))
        .filter(models.Vehicle.id == vehicle_id)
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Fordon ej hittad")
    return vehicle


@router.get("", response_model=List[VehicleOut])
def list_vehicles(
    q: Optional[str] = Query(None),
    customer_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.Vehicle).options(joinedload(models.Vehicle.customer))
    if q:
        query = query.filter(models.Vehicle.license_plate.ilike(f"%{q}%"))
    if customer_id:
        query = query.filter(models.Vehicle.customer_id == customer_id)
    return query.order_by(models.Vehicle.license_plate).all()


@router.post("", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def create_vehicle(
    body: VehicleCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    if not db.get(models.Customer, body.customer_id):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    vehicle = models.Vehicle(**body.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return db.query(models.Vehicle).options(joinedload(models.Vehicle.customer)).get(vehicle.id)


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = (
        db.query(models.Vehicle)
        .options(joinedload(models.Vehicle.customer))
        .filter(models.Vehicle.id == vehicle_id)
        .first()
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Fordon ej hittad")
    return vehicle


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    body: VehicleUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = db.get(models.Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Fordon ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    db.commit()
    db.refresh(vehicle)
    return db.query(models.Vehicle).options(joinedload(models.Vehicle.customer)).get(vehicle.id)


@router.delete("/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_vehicle(
    vehicle_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = db.get(models.Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Fordon ej hittad")
    db.delete(vehicle)
    db.commit()


# ── Svängradie ────────────────────────────────────────────────────────────────

def _turning_dims(vehicle: models.Vehicle) -> turning.TruckDims:
    dims = turning.dims_from_vehicle(vehicle)
    if dims is None:
        raise HTTPException(
            400, "Fordonet saknar hjulbas och/eller bredd – fyll i måtten för att beräkna svängradie"
        )
    return dims


def _eu_check(vehicle: models.Vehicle):
    """Manöverprovet + om max styrvinkel är ett antagande (avgör utfallet)."""
    max_angle = float(vehicle.max_steering_angle or turning.DEFAULT_MAX_STEERING)
    assumed = vehicle.max_steering_angle in (None, "")
    return turning.check_eu(_turning_dims(vehicle), max_angle), assumed


def _turning_case(vehicle: models.Vehicle, angle: Optional[float]):
    """Provfallet som både förhandsgranskningen och PDF:en ritar.

    Utan explicit ``angle`` används provläget: styrvinkeln där yttersta punkten
    löper längs 12,50 m-cirkeln. Därmed visar webbvyn exakt samma bild som PDF:en."""
    dims = _turning_dims(vehicle)
    comp, assumed = _eu_check(vehicle)
    draw_angle = angle or comp.angle or comp.max_steering_angle
    try:
        res = turning.compute(dims, draw_angle)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return dims, comp, assumed, res


@router.get("/{vehicle_id}/turning")
def get_turning(
    vehicle_id: int,
    angle: Optional[float] = Query(None, gt=0, lt=90),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Returnerar radier + konturpunkter (mm, vändcentrum i origo, y uppåt)."""
    vehicle = _load_vehicle(db, vehicle_id)
    _dims, comp, assumed, res = _turning_case(vehicle, angle)
    out = res.to_dict()
    out["compliance"] = comp.to_dict()
    out["max_steering_assumed"] = assumed
    # Kravcirklarna skickas med så att webbritningen använder samma underlag som PDF:en
    out["ref_outer"] = turning.reference_arc(turning.EU_OUTER_RADIUS)
    out["ref_inner"] = turning.reference_arc(turning.EU_INNER_RADIUS)
    return out


def _mm(value) -> str:
    """Millimetervärde med tusentalsavgränsare, t.ex. 12 450 mm."""
    if value in (None, ""):
        return ""
    return f"{float(value):,.0f} mm".replace(",", " ")


def _vehicle_label(vehicle: models.Vehicle) -> str:
    """Underrubrik till utskrifter: reg.nr · fabrikat modell · kund."""
    parts = [
        vehicle.license_plate,
        f"{vehicle.make or ''} {vehicle.model or ''}".strip(),
        vehicle.customer.name if vehicle.customer else "",
    ]
    return " · ".join(p for p in parts if p)


def _vehicle_rows(vehicle: models.Vehicle):
    """Fordonsdata för infopanelen. Tomma fält filtreras bort av draw_info_panel."""
    return [
        ("Kund", vehicle.customer.name if vehicle.customer else ""),
        ("Reg.nr", vehicle.license_plate),
        ("Fabrikat", vehicle.make),
        ("Modell", vehicle.model),
        ("Årsmodell", vehicle.year),
        ("Chassinr", vehicle.vin),
        ("Motor", vehicle.engine),
        ("Växellåda", vehicle.gearbox),
        ("Mätarställning", f"{vehicle.odometer:,} km".replace(",", " ") if vehicle.odometer else ""),
        ("Kraftuttag", vehicle.kraftuttag),
        ("Utväxling", vehicle.utvaxling),
        ("Rotation", vehicle.rotation),
        ("Medbringare", vehicle.medbringare),
        ("Hjulbas", _mm(vehicle.wheelbase_mm)),
        ("Bredd", _mm(vehicle.width_mm)),
        ("Överhäng fram", _mm(vehicle.front_overhang_mm)),
        ("Överhäng bak", _mm(vehicle.rear_overhang_mm)),
    ]


_TURNING_METHOD = (
    "Krav: fordonet ska kunna manövreras inom en cirkelring som begränsas av två koncentriska "
    "cirklar med ytterradie 12,50 m och innerradie 5,30 m, utan att någon del hamnar utanför "
    "ytterkretsen eller innanför innerkretsen ((EU) 2021/535 bilaga XIII avsnitt D).\n"
    "\n"
    "Provförfarande: styrvinkeln ställs så att fordonets yttersta punkt löper längs 12,50 m-"
    "cirkeln. I detta läge avläses fordonets minsta radie R in. Skillnaden R ut − R in är "
    "fordonets utsvängning (svepbredd) och får inte överstiga 7,20 m.\n"
    "\n"
    "Geometrisk modell (stationär lågfartssväng): vändcentrum ligger på linjen genom de fasta "
    "axlarnas geometriska mittpunkt. Med effektiv hjulbas L (främre styraxel till denna punkt) "
    "och styrvinkel δ gäller R = L / tan δ. Varje styrbar axel i ges sin ideala vinkel "
    "δi = arctan(ui / R), där ui är axelns avstånd till samma punkt. R in = R − B/2 och R ut är "
    "största avståndet från vändcentrum till karossens hörn, där B är fordonets bredd."
)


def _verdict_badge(c, x, y_top, width, passed: bool) -> float:
    """Tydlig utfallsruta överst i panelkolumnen. Returnerar underkanten."""
    h = 22
    bg = "#12a150" if passed else "#e5484d"
    c.setFillColor(colors.HexColor(bg))
    c.roundRect(x, y_top - h, width, h, 5, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(x + width / 2, y_top - 15, "GODKÄND" if passed else "EJ GODKÄND")
    return y_top - h


def _turning_draw(c, page_w, page_h, margin, vehicle, res, comp, assumed):
    """Sida 1 – manöverritningen med kravcirklarna 12,50 m / 5,30 m."""
    top = draw_header(c, page_w, "Manöverprov – svängradie",
                      _vehicle_label(vehicle), top_y=page_h - 10 * mm)

    plot_left = margin + 74 * mm
    plot_right = page_w - margin
    plot_top = top - 4 * mm
    plot_bottom = margin + 6 * mm

    span = (4.0, 90.0)
    ref_out = turning.reference_arc(turning.EU_OUTER_RADIUS, span)
    ref_in = turning.reference_arc(turning.EU_INNER_RADIUS, span)

    def at(r, deg):
        a = math.radians(deg)
        return (r * math.cos(a), r * math.sin(a))

    dim_deg = 15.0                       # stråle för utsvängningsmåttet
    anchors = [at(turning.EU_OUTER_RADIUS * 1.04, 62), at(turning.EU_OUTER_RADIUS, dim_deg)]
    # Startläget utelämnas medvetet – i provritningen ska bara provläget synas.
    all_pts = (res.arc_in + res.arc_out + res.body
               + ref_out + ref_in + anchors + [res.center])
    xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]
    min_x, max_x = min(xs), max(xs); min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    scale = min((plot_right - plot_left) / span_x, (plot_top - plot_bottom) / span_y) * 0.94
    off_x = plot_left + ((plot_right - plot_left) - span_x * scale) / 2
    off_y = plot_bottom + ((plot_top - plot_bottom) - span_y * scale) / 2

    def T(pt):
        return (off_x + (pt[0] - min_x) * scale, off_y + (pt[1] - min_y) * scale)

    def poly(pts, close=True):
        p = c.beginPath()
        p.moveTo(*T(pts[0]))
        for pt in pts[1:]:
            p.lineTo(*T(pt))
        if close:
            p.close()
        return p

    # Tillåten korridor mellan kravcirklarna
    c.setFillColor(colors.HexColor("#12a150")); c.setFillAlpha(0.10)
    c.drawPath(poly(ref_out + ref_in[::-1]), fill=1, stroke=0); c.setFillAlpha(1)

    # Fordonets faktiska svep
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.22)
    c.drawPath(poly(res.arc_out + res.arc_in[::-1]), fill=1, stroke=0); c.setFillAlpha(1)

    # Kravcirklarna
    c.setStrokeColor(colors.HexColor("#12a150")); c.setLineWidth(1.8)
    c.drawPath(poly(ref_out, close=False))
    c.drawPath(poly(ref_in, close=False))

    # Fordonets svepkanter
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.3); c.setDash(5, 3)
    c.drawPath(poly(res.arc_in, close=False))
    c.drawPath(poly(res.arc_out, close=False)); c.setDash()

    # Fordonet
    c.setFillColor(colors.HexColor("#374151"))
    for w in res.wheels:
        c.drawPath(poly(w), fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.8)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.10)
    c.drawPath(poly(res.body), fill=1, stroke=1); c.setFillAlpha(1)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.30)
    c.drawPath(poly(res.cab), fill=1, stroke=1); c.setFillAlpha(1)

    cen = T(res.center)
    c.setFillColor(colors.HexColor("#e5484d"))
    c.circle(cen[0], cen[1], 3, fill=1, stroke=0)

    # ── Utsvängningsmått (det som saknades) ──
    p_in, p_out = T(at(res.r_in, dim_deg)), T(at(res.r_out, dim_deg))
    ux, uy = math.cos(math.radians(dim_deg)), math.sin(math.radians(dim_deg))
    tx, ty = -uy * 4, ux * 4
    c.setStrokeColor(colors.HexColor("#e5484d")); c.setLineWidth(0.8); c.setDash(2, 2)
    c.line(cen[0], cen[1], p_out[0], p_out[1]); c.setDash()
    c.setLineWidth(1.6)
    c.line(p_in[0], p_in[1], p_out[0], p_out[1])
    for p in (p_in, p_out):
        c.line(p[0] - tx, p[1] - ty, p[0] + tx, p[1] + ty)
    c.setFont("Helvetica-Bold", 8.5); c.setFillColor(colors.HexColor("#e5484d"))
    c.drawString((p_in[0] + p_out[0]) / 2 + 6, (p_in[1] + p_out[1]) / 2 - 12,
                 f"Utsvängning {_mm(res.swept_width)}")

    # Etiketter vid bågarna
    def arc_label(r, deg, text, hexcol):
        p = T(at(r, deg))
        c.setFillColor(colors.HexColor(hexcol)); c.setFont("Helvetica-Bold", 8)
        c.drawString(p[0] + 4, p[1] + 3, text)

    arc_label(turning.EU_OUTER_RADIUS, 62, "KRAV  R 12,50 m", "#0f7a3d")
    arc_label(turning.EU_INNER_RADIUS, 70, "KRAV  R 5,30 m", "#0f7a3d")
    arc_label(res.r_in, 86, f"R in {_mm(res.r_in)}", "#2f6fed")

    # ── Panelkolumn ──
    px, pw = margin, 66 * mm
    py = _verdict_badge(c, px, top - 6 * mm, pw, comp.passed)

    rows = [
        ("Krav ytterradie", _mm(comp.outer_limit)),
        ("Krav innerradie", _mm(comp.inner_limit)),
        ("Styrvinkel i provet", f"{comp.angle:g}°" if comp.angle else "ej uppnåelig"),
        ("R ut uppnådd", _mm(comp.r_out)),
        ("R in uppnådd", _mm(comp.r_in)),
        ("Utsvängning", _mm(comp.swept_width)),
        ("Max utsvängning", _mm(comp.max_swept)),
    ]
    py = draw_info_panel(c, px, py - 8, pw, "Manöverprov · (EU) 2021/535 XIII D", rows,
                         accent="#12a150" if comp.passed else "#e5484d")

    py = draw_info_panel(c, px, py - 8, pw, "Fordon", [
        ("Reg.nr", vehicle.license_plate),
        ("Fabrikat", vehicle.make),
        ("Modell", vehicle.model),
        ("Chassinr", vehicle.vin),
        ("Max styrvinkel", f"{comp.max_steering_angle:g}°" + (" (antagen)" if assumed else "")),
    ])

    # Teckenförklaring
    py -= 14
    c.setFont("Helvetica-Bold", 7.5); c.setFillColor(colors.HexColor("#5a6675"))
    c.drawString(px, py, "TECKENFÖRKLARING")
    py -= 11
    for hexcol, alpha, text in [
        ("#12a150", 0.18, "Tillåten korridor 5,30 – 12,50 m"),
        ("#2f6fed", 0.30, "Fordonets svepyta"),
        ("#e5484d", 1.00, "Utsvängning R ut − R in"),
    ]:
        c.setFillColor(colors.HexColor(hexcol)); c.setFillAlpha(alpha)
        c.rect(px, py - 1, 10, 6, fill=1, stroke=0); c.setFillAlpha(1)
        c.setFillColor(colors.HexColor("#333333")); c.setFont("Helvetica", 7.5)
        c.drawString(px + 14, py, text)
        py -= 11

    # Varning om utfallet vilar på ett antagande
    if assumed:
        py -= 6
        c.setFont("Helvetica-Oblique", 7.5); c.setFillColor(colors.HexColor("#e5484d"))
        for line in [
            "OBS: fordonets max styrvinkel saknas i registret.",
            f"Beräknat med antagna {comp.max_steering_angle:g}°. Fyll i",
            "chassileverantörens värde innan inlämning.",
        ]:
            c.drawString(px, py, line)
            py -= 9


def _turning_spec(c, page_w, page_h, margin, vehicle, res, comp, assumed):
    """Sida 2 – beräkningsunderlaget: indata, axelkonfiguration, resultat, metod."""
    top = draw_header(c, page_w, "Beräkningsunderlag – manöverprov",
                      _vehicle_label(vehicle), top_y=page_h - 10 * mm)

    col_w = 84 * mm
    gap = 6 * mm
    cols = [margin, margin + col_w + gap, margin + 2 * (col_w + gap)]
    y0 = top - 6 * mm

    n_axles = len(res.axle_angles)
    n_steered = sum(1 for a in res.axle_angles if a["steered"])

    draw_info_panel(c, cols[0], y0, col_w, "Indata – fordonsgeometri", [
        ("Bredd B", _mm(vehicle.width_mm)),
        ("Överhäng fram", _mm(vehicle.front_overhang_mm)),
        ("Överhäng bak", _mm(vehicle.rear_overhang_mm)),
        ("Antal axlar", f"{n_axles} varav {n_steered} styrbara"),
        ("Effektiv hjulbas L", _mm(comp.l_eff)),
        ("Max styrvinkel", f"{comp.max_steering_angle:g}°" + (" (antagen)" if assumed else "")),
        ("Chassinr", vehicle.vin),
    ])

    axle_rows = []
    for i, a in enumerate(res.axle_angles):
        kind = f"styrd  δ={a['angle']:g}°" if a["steered"] else "fast"
        axle_rows.append((f"Axel {i+1} · {_mm(a['offset'])}", kind))
    draw_info_panel(c, cols[1], y0, col_w, "Axelkonfiguration i provläget", axle_rows)

    py = draw_info_panel(c, cols[2], y0, col_w, "Provresultat", [
        ("Styrvinkel i provet", f"{comp.angle:g}°" if comp.angle else "ej uppnåelig"),
        ("Radie till centrumlinjen R", _mm(comp.r_center)),
        ("R ut", _mm(comp.r_out)),
        ("R in", _mm(comp.r_in)),
        ("Utsvängning R ut − R in", _mm(comp.swept_width)),
    ])
    draw_info_panel(c, cols[2], py - 8, col_w, "Vid fullt styrutslag", [
        ("R ut minsta", _mm(comp.r_out_at_max)),
        ("R in minsta", _mm(comp.r_in_at_max)),
        ("Utsvängning", _mm(comp.swept_at_max)),
    ])

    # Metodbeskrivning
    y = margin + 68 * mm
    c.setFont("Helvetica-Bold", 9.5); c.setFillColor(colors.black)
    c.drawString(margin, y, "Metod och kravgrund")
    y -= 14
    draw_paragraph(c, _TURNING_METHOD, margin, y, page_w - 2 * margin,
                   font_size=8.5, leading=11.5, min_y=margin + 4 * mm)


@router.get("/{vehicle_id}/turning/pdf")
def turning_pdf(
    vehicle_id: int,
    angle: Optional[float] = Query(None, gt=0, lt=90),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    _dims, comp, assumed, res = _turning_case(vehicle, angle)

    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    margin = 15 * mm

    _turning_draw(c, page_w, page_h, margin, vehicle, res, comp, assumed)
    c.showPage()
    _turning_spec(c, page_w, page_h, margin, vehicle, res, comp, assumed)

    c.save()
    buf.seek(0)
    filename = f"svangradie-{vehicle.license_plate}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Axeltryck / tankplacering ─────────────────────────────────────────────────

def _load_geometry(vehicle, wheelbase_override):
    """Härleder lasthjulbasen (framaxel → bakaxelgruppens centrum) och de verkliga
    axeloffseten (normaliserade så framaxeln = 0) för sidvys-ritningen."""
    raw = getattr(vehicle, "axles", None)
    offs = []
    if raw:
        offs = sorted(float(a.get("offset_mm", a.get("offset", 0))) for a in raw)
        offs = [o - offs[0] for o in offs]      # normalisera framaxel till 0
    if wheelbase_override:
        L = float(wheelbase_override)
    elif len(offs) >= 2:
        rear = offs[1:]                          # bakaxelgrupp
        L = sum(rear) / len(rear)                # boggi-centrum bakom framaxeln
    elif vehicle.wheelbase_mm:
        L = float(vehicle.wheelbase_mm)
    else:
        L = None
    if len(offs) < 2:
        offs = [0.0, L] if L else []
    return L, offs


def _axle_load(vehicle, wheelbase, **kw):
    L, _offs = _load_geometry(vehicle, wheelbase)
    if not L:
        raise HTTPException(400, "Hjulbas krävs – fyll i fordonets hjulbas/axlar eller ange den")
    try:
        return axleload.compute(wheelbase=float(L), **kw)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{vehicle_id}/axle-load")
def get_axle_load(
    vehicle_id: int,
    empty_front: float = Query(...), empty_rear: float = Query(...), empty_total: float = Query(...),
    tank_length: float = Query(...), loaded_total: float = Query(...),
    desired_front: float = Query(...), desired_rear: float = Query(...),
    max_front: float = Query(...), max_rear: float = Query(...),
    wheelbase: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    L, offs = _load_geometry(vehicle, wheelbase)
    r = _axle_load(
        vehicle, wheelbase,
        empty_front=empty_front, empty_rear=empty_rear, empty_total=empty_total,
        tank_length=tank_length, loaded_total=loaded_total,
        desired_front=desired_front, desired_rear=desired_rear,
        max_front=max_front, max_rear=max_rear,
    )
    out = r.to_dict()
    out["axle_offsets"] = offs
    out["front_overhang"] = float(vehicle.front_overhang_mm or 0)
    axle2 = offs[1] if len(offs) >= 2 else L
    out["cg_axle2"] = round(r.cg - axle2, 1)      # TP mätt från andra axeln
    out["silhouette"] = axleload.silhouette(
        float(vehicle.front_overhang_mm or 0), offs, r.tank_front, r.tank_length)
    out["dimensions"] = axleload.dimensions(
        float(vehicle.front_overhang_mm or 0), offs, L, r.tank_front, r.tank_length, r.cg)
    return out


@router.get("/{vehicle_id}/axle-load/pdf")
def axle_load_pdf(
    vehicle_id: int,
    empty_front: float = Query(...), empty_rear: float = Query(...), empty_total: float = Query(...),
    tank_length: float = Query(...), loaded_total: float = Query(...),
    desired_front: float = Query(...), desired_rear: float = Query(...),
    max_front: float = Query(...), max_rear: float = Query(...),
    wheelbase: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    L, offs = _load_geometry(vehicle, wheelbase)
    r = _axle_load(
        vehicle, wheelbase,
        empty_front=empty_front, empty_rear=empty_rear, empty_total=empty_total,
        tank_length=tank_length, loaded_total=loaded_total,
        desired_front=desired_front, desired_rear=desired_rear,
        max_front=max_front, max_rear=max_rear,
    )

    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    margin = 15 * mm
    veh_label = f"{vehicle.license_plate} · {vehicle.make or ''} {vehicle.model or ''}".strip(" ·")
    top = draw_header(c, page_w, "Axeltryck – tankplacering", veh_label, top_y=page_h - 10 * mm)

    L = r.wheelbase
    rear_ref = L   # bakaxelgruppens centrum = lastreferens (måtten pekar hit)

    def kg(v):
        return f"{v:,.0f} kg".replace(",", " ")

    def mm_(v):
        return f"{v:,.0f} mm".replace(",", " ")

    # ── Sidvy (höger) med lastbilssiluett ──
    sil = axleload.silhouette(float(vehicle.front_overhang_mm or 0), offs, r.tank_front, r.tank_length)
    rW = sil["wheel_r"]; beam_bot, beam_top = sil["beam_bot"], sil["beam_top"]
    tank_bot, tank_top = sil["tank_bot"], sil["tank_top"]
    cab_top = max(p[1] for p in sil["cab"])
    dims = axleload.dimensions(float(vehicle.front_overhang_mm or 0), offs, L,
                               r.tank_front, r.tank_length, r.cg)
    x_axles = offs if offs else [0.0, L]
    x0 = min(0.0, r.tank_front, min(x_axles), sil["cab"][0][0]) - 900
    x1 = max(rear_ref, r.tank_front + r.tank_length, max(x_axles)) + 1000
    y0 = min(-900.0, *(d["y"] for d in dims)) - 60
    y1 = max(cab_top + 250, *(d["y"] for d in dims)) + 160

    plot_left, plot_right = margin + 92 * mm, page_w - margin
    plot_top, plot_bottom = top - 4 * mm, margin + 6 * mm
    scale = min((plot_right - plot_left) / (x1 - x0), (plot_top - plot_bottom) / (y1 - y0)) * 0.95
    ox = plot_left + ((plot_right - plot_left) - (x1 - x0) * scale) / 2
    oy = plot_bottom + ((plot_top - plot_bottom) - (y1 - y0) * scale) / 2

    def T(x, y):
        return (ox + (x - x0) * scale, oy + (y - y0) * scale)

    def wpoly(pts, close=True):
        p = c.beginPath(); p.moveTo(*T(*pts[0]))
        for q in pts[1:]:
            p.lineTo(*T(*q))
        if close:
            p.close()
        return p

    # underlag
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.8)
    c.line(*T(x0, 0), *T(x1, 0))
    # chassiram
    c.setFillColor(colors.HexColor("#94a3b8"))
    (bx0, by0), (bx1, by1) = T(min(x_axles) - rW, beam_bot), T(max(x_axles) + rW, beam_top)
    c.rect(bx0, by0, bx1 - bx0, by1 - by0, fill=1, stroke=0)
    # tank + baffler
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.18)
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.6)
    (tx0, ty0), (tx1, ty1) = T(r.tank_front, tank_bot), T(r.tank_front + r.tank_length, tank_top)
    c.roundRect(tx0, ty0, tx1 - tx0, ty1 - ty0, min(40, (ty1 - ty0) / 2), fill=1, stroke=1)
    c.setFillAlpha(1)
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(0.6)
    for b in sil["baffles"]:
        c.line(*T(*b[0]), *T(*b[1]))
    # hjul
    for ax in x_axles:
        cx, cy = T(ax, rW)
        c.setFillColor(colors.HexColor("#1f2937")); c.circle(cx, cy, rW * scale, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#9aa6b2")); c.circle(cx, cy, rW * scale * 0.40, fill=1, stroke=0)
    # stänkskärmar
    c.setStrokeColor(colors.HexColor("#374151")); c.setLineWidth(1.6)
    for f in sil["fenders"]:
        c.drawPath(wpoly(f, close=False), fill=0, stroke=1)
    # hytt
    c.setFillColor(colors.HexColor("#cbd5e1")); c.setStrokeColor(colors.HexColor("#475569")); c.setLineWidth(1.4)
    c.drawPath(wpoly(sil["cab"]), fill=1, stroke=1)
    # vindruta
    c.setFillColor(colors.HexColor("#7dd3fc")); c.setFillAlpha(0.55)
    c.drawPath(wpoly(sil["windshield"]), fill=1, stroke=0); c.setFillAlpha(1)
    # stötfångare
    c.setFillColor(colors.HexColor("#475569"))
    c.drawPath(wpoly(sil["bumper"]), fill=1, stroke=0)

    # tyngdpunkt
    c.setStrokeColor(colors.HexColor("#e5484d")); c.setLineWidth(1.4); c.setDash(4, 3)
    c.line(*T(r.cg, beam_top), *T(r.cg, tank_top + 520)); c.setDash()
    cgx, cgy = T(r.cg, tank_top + 520)
    c.setFillColor(colors.HexColor("#e5484d")); c.circle(cgx, cgy, 4, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8); c.drawString(cgx + 6, cgy - 3, "TP")
    wx, wy = T(r.cg, tank_top + 560)
    c.setFont("Helvetica-Bold", 8.5); c.drawCentredString(wx, wy, kg(r.tank_weight))

    def dim(xa, xb, yl, label, accent=False):
        ya = T(xa, yl)[1]
        col_ = colors.HexColor("#e5484d") if accent else colors.HexColor("#5a6675")
        c.setStrokeColor(col_); c.setLineWidth(0.7)
        c.line(*T(xa, yl), *T(xb, yl))
        c.line(T(xa, yl)[0], ya - 4, T(xa, yl)[0], ya + 4)
        c.line(T(xb, yl)[0], ya - 4, T(xb, yl)[0], ya + 4)
        c.setFont("Helvetica", 8); c.setFillColor(col_)
        c.drawCentredString((T(xa, yl)[0] + T(xb, yl)[0]) / 2, ya + 3, label)

    for d in dims:
        dim(d["a"], d["b"], d["y"], d["label"], accent=d.get("accent", False))

    # axeletiketter
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 8.5)
    c.drawCentredString(T(0, -150)[0], T(0, -150)[1], "Framaxel")
    c.drawCentredString(T(rear_ref, -150)[0], T(rear_ref, -150)[1], "Bakaxel")

    # ── Vikttabell (vänster) ──
    px = margin
    tw = 86 * mm
    col = [px + 30 * mm, px + 52 * mm, px + 74 * mm]   # Fram, Bak, Total kolumn-högerkant
    yy = top - 8 * mm
    c.setFont("Helvetica-Bold", 11); c.setFillColor(colors.black)
    c.drawString(px, yy, "Viktfördelning")
    yy -= 6
    c.setStrokeColor(colors.HexColor("#E2001A")); c.setLineWidth(1)
    c.line(px, yy, px + tw, yy); yy -= 14

    # rubrikrad
    c.setFont("Helvetica-Bold", 8.5); c.setFillColor(colors.HexColor("#5a6675"))
    c.drawRightString(col[0], yy, "Fram")
    c.drawRightString(col[1], yy, "Bak")
    c.drawRightString(col[2], yy, "Totalt")
    yy -= 4
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.6); c.line(px, yy, px + tw, yy); yy -= 12

    def trow(label, f, b, t, bold=False, color=colors.black):
        nonlocal yy
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#333333")); c.drawString(px, yy, label)
        c.setFillColor(color)
        c.drawRightString(col[0], yy, kg(f))
        c.drawRightString(col[1], yy, kg(b))
        c.drawRightString(col[2], yy, kg(t))
        yy -= 13

    trow("Tomvikt", r.empty_front, r.empty_rear, r.empty_total)
    trow("Lastad", r.load_front, r.load_rear, r.loaded_total, bold=True)
    trow("Max tillåten", r.max_front, r.max_rear, r.max_total)
    # utnyttjande
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.6); c.line(px, yy + 4, px + tw, yy + 4)
    over = colors.HexColor("#e5484d")
    c.setFont("Helvetica-Bold", 8.5); c.setFillColor(colors.HexColor("#333333"))
    c.drawString(px, yy, "Utnyttjande")
    c.setFillColor(over if r.front_util > 100 else colors.HexColor("#12a150")); c.drawRightString(col[0], yy, f"{r.front_util:g}%")
    c.setFillColor(over if r.rear_util > 100 else colors.HexColor("#12a150")); c.drawRightString(col[1], yy, f"{r.rear_util:g}%")
    c.setFillColor(over if r.total_util > 100 else colors.HexColor("#12a150")); c.drawRightString(col[2], yy, f"{r.total_util:g}%")
    yy -= 20

    # tankdata
    axle2 = offs[1] if len(offs) >= 2 else L
    c.setFillColor(colors.black); c.setFont("Helvetica-Bold", 9.5); c.drawString(px, yy, "Tankplacering"); yy -= 14
    for label, value in [
        ("Tankvikt", kg(r.tank_weight)),
        ("Tanklängd", mm_(r.tank_length)),
        ("Tyngdpunkt bakom andra axeln", mm_(r.cg - axle2)),
        ("Tyngdpunkt bakom framaxeln", mm_(r.cg)),
        ("Tankens framkant bakom framaxel", mm_(r.tank_front)),
    ]:
        c.setFont("Helvetica", 8.5); c.setFillColor(colors.HexColor("#5a6675")); c.drawString(px, yy, label)
        c.setFont("Helvetica-Bold", 8.5); c.setFillColor(colors.black); c.drawRightString(px + tw, yy, value)
        yy -= 13

    if r.warnings:
        yy -= 4
        c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#e5484d"))
        for w in r.warnings:
            c.drawString(px, yy, "⚠ " + w); yy -= 11

    c.save()
    buf.seek(0)
    filename = f"axeltryck-{vehicle.license_plate}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

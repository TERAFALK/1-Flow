import io
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
from ..pdf_utils import draw_header
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

def _turning_for(vehicle: models.Vehicle, angle: Optional[float]) -> turning.TurningResult:
    dims = turning.dims_from_vehicle(vehicle)
    if dims is None:
        raise HTTPException(
            400, "Fordonet saknar hjulbas och/eller bredd – fyll i måtten för att beräkna svängradie"
        )
    steer = angle or vehicle.max_steering_angle or 20.0
    try:
        return turning.compute(dims, steer)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{vehicle_id}/turning")
def get_turning(
    vehicle_id: int,
    angle: Optional[float] = Query(None, gt=0, lt=90),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    """Returnerar radier + konturpunkter (mm, vändcentrum i origo, y uppåt)."""
    vehicle = _load_vehicle(db, vehicle_id)
    return _turning_for(vehicle, angle).to_dict()


@router.get("/{vehicle_id}/turning/pdf")
def turning_pdf(
    vehicle_id: int,
    angle: Optional[float] = Query(None, gt=0, lt=90),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    res = _turning_for(vehicle, angle)

    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    margin = 15 * mm

    veh_label = f"{vehicle.license_plate} · {vehicle.make or ''} {vehicle.model or ''}".strip(" ·")
    top = draw_header(c, page_w, "Svängradie", veh_label, top_y=page_h - 10 * mm)

    # ── Ritområde (höger del av sidan) ──
    plot_left = margin + 78 * mm            # lämna plats för infopanel till vänster
    plot_right = page_w - margin
    plot_top = top - 4 * mm
    plot_bottom = margin

    # Samla alla punkter för att passa in i ritområdet
    all_pts = res.arc_in + res.arc_out + res.body + res.ghost + [res.center]
    xs = [p[0] for p in all_pts]; ys = [p[1] for p in all_pts]
    min_x, max_x = min(xs), max(xs); min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0
    scale = min((plot_right - plot_left) / span_x, (plot_top - plot_bottom) / span_y) * 0.94
    # Centrera
    off_x = plot_left + ((plot_right - plot_left) - span_x * scale) / 2
    off_y = plot_bottom + ((plot_top - plot_bottom) - span_y * scale) / 2

    def T(pt):
        return (off_x + (pt[0] - min_x) * scale, off_y + (pt[1] - min_y) * scale)

    def poly(pts, close=True):
        p = c.beginPath()
        first = T(pts[0]); p.moveTo(*first)
        for pt in pts[1:]:
            p.lineTo(*T(pt))
        if close:
            p.close()
        return p

    # Svepband (fyllt)
    band = res.arc_out + res.arc_in[::-1]
    c.setFillColor(colors.HexColor("#2f6fed"))
    c.setFillAlpha(0.10)
    c.drawPath(poly(band), fill=1, stroke=0)
    c.setFillAlpha(1)

    # Radiella referenslinjer
    cen = T(res.center)
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.6); c.setDash(3, 3)
    c.line(cen[0], cen[1], *T(res.arc_out[0]))
    c.line(cen[0], cen[1], *T(res.arc_out[-1]))
    c.setDash()

    # Bågar
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.6); c.drawPath(poly(res.arc_out, close=False))
    c.setStrokeColor(colors.HexColor("#12a150")); c.setLineWidth(1.6); c.drawPath(poly(res.arc_in, close=False))

    # Ghost (startläge)
    c.setStrokeColor(colors.HexColor("#9aa6b2")); c.setLineWidth(1.0); c.setDash(4, 3)
    c.drawPath(poly(res.ghost), fill=0, stroke=1); c.setDash()

    # Lastbil – hjul underst
    c.setFillColor(colors.HexColor("#374151"))
    for w in res.wheels:
        c.drawPath(poly(w), fill=1, stroke=0)
    # chassi
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.8)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.08)
    c.drawPath(poly(res.body), fill=1, stroke=1); c.setFillAlpha(1)
    # hytt
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.28)
    c.drawPath(poly(res.cab), fill=1, stroke=1); c.setFillAlpha(1)

    # Vändcentrum
    c.setFillColor(colors.HexColor("#e5484d"))
    c.circle(cen[0], cen[1], 3, fill=1, stroke=0)

    # ── Infopanel (vänster) ──
    px, pw = margin, 70 * mm
    py_top = top - 6 * mm
    n_axles = len(res.axle_angles)
    n_steered = sum(1 for a in res.axle_angles if a["steered"])
    rows = [
        ("Styrvinkel fram", f"{res.steering_angle:g}°"),
        ("Antal axlar", f"{n_axles} ({n_steered} styrbara)"),
        ("Bredd", f"{vehicle.width_mm} mm"),
        ("Ytterradie R ut", f"{res.r_out:,.0f} mm".replace(",", " ")),
        ("Innerradie R in", f"{res.r_in:,.0f} mm".replace(",", " ")),
        ("Framaxel R fram", f"{res.r_front:,.0f} mm".replace(",", " ")),
        ("Svepbredd", f"{res.swept_width:,.0f} mm".replace(",", " ")),
    ]
    # Extra rad per styrbar axel utöver den främre
    for i, a in enumerate(res.axle_angles):
        if a["steered"] and i > 0:
            rows.append((f"Styrvinkel axel {i+1}", f"{a['angle']:g}°"))
    ph = 16 + len(rows) * 15
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.05)
    c.roundRect(px, py_top - ph, pw, ph, 6, fill=1, stroke=0); c.setFillAlpha(1)
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.8)
    c.roundRect(px, py_top - ph, pw, ph, 6, fill=0, stroke=1)
    yy = py_top - 15
    for label, value in rows:
        c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#5a6675"))
        c.drawString(px + 8, yy, label)
        c.setFont("Helvetica-Bold", 9); c.setFillColor(colors.black)
        c.drawRightString(px + pw - 8, yy, value)
        yy -= 15

    c.save()
    buf.seek(0)
    filename = f"svangradie-{vehicle.license_plate}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Axeltryck / tankplacering ─────────────────────────────────────────────────

def _axle_load(vehicle, wheelbase, empty_front, empty_rear, tank_weight,
               tank_length, tank_front, target_rear):
    L = wheelbase or (vehicle.wheelbase_mm if vehicle else None)
    if not L:
        raise HTTPException(400, "Hjulbas krävs (ange den eller fyll i fordonets hjulbas)")
    try:
        return axleload.compute(
            wheelbase=float(L),
            empty_front=float(empty_front), empty_rear=float(empty_rear),
            tank_weight=float(tank_weight), tank_length=float(tank_length),
            tank_front=None if tank_front is None else float(tank_front),
            target_rear=None if target_rear is None else float(target_rear),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/{vehicle_id}/axle-load")
def get_axle_load(
    vehicle_id: int,
    empty_front: float = Query(...), empty_rear: float = Query(...),
    tank_weight: float = Query(...), tank_length: float = Query(...),
    tank_front: Optional[float] = Query(None),
    target_rear: Optional[float] = Query(None),
    wheelbase: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    return _axle_load(vehicle, wheelbase, empty_front, empty_rear,
                      tank_weight, tank_length, tank_front, target_rear).to_dict()


@router.get("/{vehicle_id}/axle-load/pdf")
def axle_load_pdf(
    vehicle_id: int,
    empty_front: float = Query(...), empty_rear: float = Query(...),
    tank_weight: float = Query(...), tank_length: float = Query(...),
    tank_front: Optional[float] = Query(None),
    target_rear: Optional[float] = Query(None),
    wheelbase: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    vehicle = _load_vehicle(db, vehicle_id)
    r = _axle_load(vehicle, wheelbase, empty_front, empty_rear,
                   tank_weight, tank_length, tank_front, target_rear)

    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    margin = 15 * mm
    veh_label = f"{vehicle.license_plate} · {vehicle.make or ''} {vehicle.model or ''}".strip(" ·")
    top = draw_header(c, page_w, "Axeltryck – tankplacering", veh_label, top_y=page_h - 10 * mm)

    # ── Sidvy (höger) ──
    L = r.wheelbase
    rW = 520.0                       # visuell hjulradie (mm)
    beam_bot, beam_top = rW + 120, rW + 300
    tankH = 2000.0
    tank_bot, tank_top = beam_top + 40, beam_top + 40 + tankH
    x0 = min(0.0, r.tank_front) - 900
    x1 = max(L, r.tank_front + r.tank_length) + 900
    y0, y1 = -700.0, tank_top + 700

    plot_left, plot_right = margin + 80 * mm, page_w - margin
    plot_top, plot_bottom = top - 4 * mm, margin
    scale = min((plot_right - plot_left) / (x1 - x0), (plot_top - plot_bottom) / (y1 - y0)) * 0.95
    ox = plot_left + ((plot_right - plot_left) - (x1 - x0) * scale) / 2
    oy = plot_bottom + ((plot_top - plot_bottom) - (y1 - y0) * scale) / 2

    def T(x, y):
        return (ox + (x - x0) * scale, oy + (y - y0) * scale)

    # Mark / underlag
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.8)
    c.line(*T(x0, 0), *T(x1, 0))

    # Chassiram
    c.setFillColor(colors.HexColor("#94a3b8"))
    (bx0, by0), (bx1, by1) = T(-rW, beam_bot), T(L + rW, beam_top)
    c.rect(bx0, by0, bx1 - bx0, by1 - by0, fill=1, stroke=0)

    # Tank (cylinder i sidvy)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.18)
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.6)
    (tx0, ty0), (tx1, ty1) = T(r.tank_front, tank_bot), T(r.tank_front + r.tank_length, tank_top)
    c.roundRect(tx0, ty0, tx1 - tx0, ty1 - ty0, min(40, (ty1 - ty0) / 2), fill=1, stroke=1)
    c.setFillAlpha(1)

    # Hjul
    c.setFillColor(colors.HexColor("#374151"))
    for ax in (0.0, L):
        cx, cy = T(ax, rW)
        c.circle(cx, cy, rW * scale, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#9aa6b2")); c.circle(cx, cy, rW * scale * 0.42, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#374151"))

    # Tyngdpunkt (CG)
    c.setStrokeColor(colors.HexColor("#e5484d")); c.setLineWidth(1.4); c.setDash(4, 3)
    c.line(*T(r.cg, beam_top), *T(r.cg, tank_top + 500)); c.setDash()
    cgx, cgy = T(r.cg, tank_top + 500)
    c.setFillColor(colors.HexColor("#e5484d"))
    c.circle(cgx, cgy, 4, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8); c.drawCentredString(cgx, cgy + 8, "TP")

    # Måttlinjer: hjulbas L (under) och placering a (över)
    def dim(xa, xb, yl, label):
        ya = T(xa, yl)[1]
        c.setStrokeColor(colors.HexColor("#5a6675")); c.setLineWidth(0.7)
        c.line(*T(xa, yl), *T(xb, yl))
        c.line(T(xa, yl)[0], ya - 4, T(xa, yl)[0], ya + 4)
        c.line(T(xb, yl)[0], ya - 4, T(xb, yl)[0], ya + 4)
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#5a6675"))
        c.drawCentredString((T(xa, yl)[0] + T(xb, yl)[0]) / 2, ya + 3, label)

    dim(0, L, -480, f"Hjulbas {L:,.0f} mm".replace(",", " "))
    dim(0, r.cg, tank_top + 640, f"a = {r.cg:,.0f} mm".replace(",", " "))

    # Axelbeteckningar med last under respektive hjul
    for ax, name, load in ((0.0, "Framaxel", r.front_load), (L, "Bakaxel", r.rear_load)):
        lx = T(ax, 0)[0]
        c.setFont("Helvetica-Bold", 8.5); c.setFillColor(colors.black)
        c.drawCentredString(lx, T(ax, -150)[1], name)
        c.setFont("Helvetica", 8); c.setFillColor(colors.HexColor("#e5484d"))
        c.drawCentredString(lx, T(ax, -300)[1], f"{load:,.0f} kg".replace(",", " "))
    c.setFillColor(colors.black)

    # ── Infopanel (vänster) ──
    px, pw = margin, 72 * mm
    py_top = top - 6 * mm

    def kg(v):
        return f"{v:,.0f} kg".replace(",", " ")

    rows = [
        ("Hjulbas", f"{L:,.0f} mm".replace(",", " ")),
        ("Tomvikt fram", kg(r.empty_front)),
        ("Tomvikt bak", kg(r.empty_rear)),
        ("Tankvikt", kg(r.tank_weight)),
        ("Tanklängd", f"{r.tank_length:,.0f} mm".replace(",", " ")),
        ("Tank framkant", f"{r.tank_front:,.0f} mm".replace(",", " ")),
        ("Tyngdpunkt (a)", f"{r.cg:,.0f} mm".replace(",", " ")),
        ("__sep__", ""),
        ("Axeltryck FRAM", kg(r.front_load) + f"  ({r.front_pct:g}%)"),
        ("Axeltryck BAK", kg(r.rear_load) + f"  ({r.rear_pct:g}%)"),
        ("Totalvikt", kg(r.total)),
    ]
    ph = 16 + len(rows) * 15
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.05)
    c.roundRect(px, py_top - ph, pw, ph, 6, fill=1, stroke=0); c.setFillAlpha(1)
    c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.8)
    c.roundRect(px, py_top - ph, pw, ph, 6, fill=0, stroke=1)
    yy = py_top - 15
    for label, value in rows:
        if label == "__sep__":
            c.setStrokeColor(colors.HexColor("#c3ccd6")); c.setLineWidth(0.6)
            c.line(px + 8, yy + 4, px + pw - 8, yy + 4); yy -= 15; continue
        bold = label.startswith("Axeltryck") or label == "Totalvikt"
        c.setFont("Helvetica", 9); c.setFillColor(colors.HexColor("#5a6675"))
        c.drawString(px + 8, yy, label)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        c.setFillColor(colors.HexColor("#e5484d") if bold else colors.black)
        c.drawRightString(px + pw - 8, yy, value)
        yy -= 15

    # Varningar
    if r.warnings:
        c.setFont("Helvetica-Oblique", 8); c.setFillColor(colors.HexColor("#e5484d"))
        wy = py_top - ph - 10
        for w in r.warnings:
            c.drawString(px, wy, "⚠ " + w); wy -= 11

    c.save()
    buf.seek(0)
    filename = f"axeltryck-{vehicle.license_plate}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

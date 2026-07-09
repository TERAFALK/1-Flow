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

    # Lastbil
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(1.8)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.08)
    c.drawPath(poly(res.body), fill=1, stroke=1); c.setFillAlpha(1)
    c.setFillColor(colors.HexColor("#2f6fed")); c.setFillAlpha(0.20)
    c.drawPath(poly(res.cab), fill=1, stroke=0); c.setFillAlpha(1)
    c.setStrokeColor(colors.HexColor("#2f6fed")); c.setLineWidth(3.5)
    c.line(*T(res.axle_front[0]), *T(res.axle_front[1]))
    c.line(*T(res.axle_rear[0]), *T(res.axle_rear[1]))

    # Vändcentrum
    c.setFillColor(colors.HexColor("#e5484d"))
    c.circle(cen[0], cen[1], 3, fill=1, stroke=0)

    # ── Infopanel (vänster) ──
    px, pw = margin, 70 * mm
    py_top = top - 6 * mm
    rows = [
        ("Styrvinkel", f"{res.steering_angle:g}°"),
        ("Hjulbas", f"{vehicle.wheelbase_mm} mm"),
        ("Bredd", f"{vehicle.width_mm} mm"),
        ("Ytterradie R ut", f"{res.r_out:,.0f} mm".replace(",", " ")),
        ("Innerradie R in", f"{res.r_in:,.0f} mm".replace(",", " ")),
        ("Framaxel R fram", f"{res.r_front:,.0f} mm".replace(",", " ")),
        ("Svepbredd", f"{res.swept_width:,.0f} mm".replace(",", " ")),
    ]
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

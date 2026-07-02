import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from ..database import get_db
from ..deps import get_current_user
from ..models import Purchase, WorkOrder, Settings, User
from ..schemas import PurchaseCreate, PurchaseUpdate, PurchaseOut
from ..pdf_utils import draw_header

router = APIRouter(prefix="/api/work-orders", tags=["purchases"])


def _next_purchase_number(db: Session) -> str:
    from datetime import datetime
    year = datetime.utcnow().year
    last = db.query(Purchase).filter(
        Purchase.purchase_number.like(f"INK-{year}-%")
    ).order_by(Purchase.purchase_number.desc()).first()
    n = 1
    if last and last.purchase_number:
        try:
            n = int(last.purchase_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            pass
    return f"INK-{year}-{n:04d}"


@router.get("/{order_id}/purchases", response_model=List[PurchaseOut])
def list_purchases(order_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    return db.query(Purchase).filter(Purchase.work_order_id == order_id).order_by(Purchase.id).all()


@router.post("/{order_id}/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(
    order_id: int,
    body: PurchaseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")

    data = body.model_dump()
    if not data.get("purchase_number"):
        mode = db.get(Settings, "purchase_number_mode")
        if not mode or mode.value == "auto":
            data["purchase_number"] = _next_purchase_number(db)
        else:
            raise HTTPException(400, "Inköpsnummer krävs (manuellt läge)")

    purchase = Purchase(work_order_id=order_id, **data)
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.put("/{order_id}/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    order_id: int,
    purchase_id: int,
    body: PurchaseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    purchase = db.query(Purchase).filter(
        Purchase.id == purchase_id, Purchase.work_order_id == order_id
    ).first()
    if not purchase:
        raise HTTPException(404, "Inköp ej hittat")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(purchase, k, v)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.get("/{order_id}/purchases/pdf")
def purchases_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(404, "Arbetsorder ej hittad")
    purchases = db.query(Purchase).filter(Purchase.work_order_id == order_id).order_by(Purchase.id).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    subtitle = wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")
    y = draw_header(c, page_w, "Inköp", subtitle)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, y, f"Ärende: {(wo.description or '')[:90]}")
    c.setFillColor(colors.black)
    y -= 20

    col_x = {
        "nr": margin,
        "desc": margin + 27 * mm,
        "art": margin + 76 * mm,
        "sup": margin + 100 * mm,
        "qty": margin + 128 * mm,   # högerjusteras mot +138
        "week": margin + 141 * mm,
        "status": margin + 153 * mm,
    }

    def header_row(yy):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#1a1a1a"))
        c.rect(margin, yy - 14, page_w - 2 * margin, 16, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.drawString(col_x["nr"], yy - 10, "Inköpsnr")
        c.drawString(col_x["desc"], yy - 10, "Benämning")
        c.drawString(col_x["art"], yy - 10, "Art.nr")
        c.drawString(col_x["sup"], yy - 10, "Leverantör")
        c.drawString(col_x["qty"], yy - 10, "Antal")
        c.drawString(col_x["week"], yy - 10, "Vecka")
        c.drawString(col_x["status"], yy - 10, "Status")
        c.setFillColor(colors.black)
        return yy - 18

    y = header_row(y)
    c.setFont("Helvetica", 8.5)
    row_h = 16
    if not purchases:
        c.setFillColor(colors.HexColor("#666666"))
        c.drawString(margin, y - 8, "Inga inköp registrerade")
        c.setFillColor(colors.black)
    for p in purchases:
        if y < 25 * mm:
            c.showPage()
            y = draw_header(c, page_w, "Inköp", subtitle)
            y -= 10
            y = header_row(y)
            c.setFont("Helvetica", 8.5)
        c.drawString(col_x["nr"], y - 8, (p.purchase_number or "")[:14])
        c.drawString(col_x["desc"], y - 8, (p.description or "")[:28])
        c.drawString(col_x["art"], y - 8, (p.article_number or "")[:13])
        c.drawString(col_x["sup"], y - 8, (p.supplier or "")[:16])
        c.drawRightString(col_x["qty"] + 10 * mm, y - 8, f"{float(p.quantity or 0):g}")
        c.drawString(col_x["week"], y - 8, f"v.{p.delivery_week}" if p.delivery_week else "")
        c.drawString(col_x["status"], y - 8, (p.status.value if p.status else "").capitalize())
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y - row_h + 2, page_w - margin, y - row_h + 2)
        c.setStrokeColor(colors.black)
        y -= row_h

    c.save()
    buf.seek(0)
    filename = f"inkop-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{order_id}/purchases/{purchase_id}", status_code=204)
def delete_purchase(
    order_id: int,
    purchase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    purchase = db.query(Purchase).filter(
        Purchase.id == purchase_id, Purchase.work_order_id == order_id
    ).first()
    if not purchase:
        raise HTTPException(404, "Inköp ej hittat")
    db.delete(purchase)
    db.commit()

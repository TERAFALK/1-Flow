import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from ..database import get_db
from ..deps import get_current_user
from ..models import Purchase, PurchaseLine, WorkOrder, Settings, User, Article
from ..schemas import PurchaseCreate, PurchaseUpdate, PurchaseOut
from ..pdf_utils import draw_header

router = APIRouter(prefix="/api/work-orders", tags=["purchases"])

_LOAD = [joinedload(Purchase.lines).joinedload(PurchaseLine.article)]


def _get(db: Session, order_id: int, purchase_id: int) -> Purchase:
    purchase = (
        db.query(Purchase)
        .options(*_LOAD)
        .filter(Purchase.id == purchase_id, Purchase.work_order_id == order_id)
        .first()
    )
    if not purchase:
        raise HTTPException(404, "Inköp ej hittat")
    return purchase


def _resolve_line_article(db: Session, line: dict) -> None:
    """Om en inköpsrad saknar lagerartikel men har ett artikelnummer angivet,
    kopplas den till en befintlig artikel med det numret – eller så skapas en ny
    artikel i registret. Muterar ``line`` in-place (sätter article_id).
    """
    if line.get("article_id"):
        return
    art_no = (line.get("article_number") or "").strip()
    if not art_no:
        return
    existing = (
        db.query(Article)
        .filter(Article.article_number.ilike(art_no))
        .first()
    )
    if existing:
        line["article_id"] = existing.id
        return
    article = Article(
        article_number=art_no,
        name=(line.get("description") or "").strip() or art_no,
        unit=line.get("unit") or "st",
    )
    db.add(article)
    db.flush()
    line["article_id"] = article.id


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
    return (
        db.query(Purchase).options(*_LOAD)
        .filter(Purchase.work_order_id == order_id)
        .order_by(Purchase.id)
        .all()
    )


@router.post("/{order_id}/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(
    order_id: int,
    body: PurchaseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")

    data = body.model_dump(exclude={"lines"})
    if not data.get("purchase_number"):
        mode = db.get(Settings, "purchase_number_mode")
        if not mode or mode.value == "auto":
            data["purchase_number"] = _next_purchase_number(db)
        else:
            raise HTTPException(400, "Inköpsnummer krävs (manuellt läge)")

    purchase = Purchase(work_order_id=order_id, **data)
    db.add(purchase)
    db.flush()
    for line in body.lines:
        line_data = line.model_dump()
        _resolve_line_article(db, line_data)
        db.add(PurchaseLine(purchase_id=purchase.id, **line_data))
    db.commit()
    return _get(db, order_id, purchase.id)


@router.put("/{order_id}/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    order_id: int,
    purchase_id: int,
    body: PurchaseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    purchase = _get(db, order_id, purchase_id)
    data = body.model_dump(exclude_unset=True)
    lines = data.pop("lines", None)
    for k, v in data.items():
        setattr(purchase, k, v)
    if lines is not None:
        # Replace the whole set of lines with the provided selection
        purchase.lines.clear()
        db.flush()
        for line in lines:
            _resolve_line_article(db, line)
            db.add(PurchaseLine(purchase_id=purchase.id, **line))
    db.commit()
    return _get(db, order_id, purchase_id)


_STATUS_LABELS = {
    "ej_beställd": "Ej beställd", "beställd": "Beställd",
    "inlevererad": "Inlevererad", "avbeställd": "Avbeställd",
}


def _draw_purchase(c, page_w, margin, y, p, new_page_if_needed):
    y = new_page_if_needed(y, needed=30)
    # Purchase header
    c.setFont("Helvetica-Bold", 10.5)
    header = p.purchase_number or "Inköp"
    if p.supplier:
        header += f" · {p.supplier}"
    c.drawString(margin, y - 12, header)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    meta = _STATUS_LABELS.get(p.status.value if p.status else "", "")
    if p.delivery_week:
        meta += f" · Leveransvecka {p.delivery_week}"
    c.drawRightString(page_w - margin, y - 12, meta)
    c.setFillColor(colors.black)
    y -= 20
    if p.description:
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(margin, y - 8, (p.description or "")[:100])
        y -= 14

    # Lines table
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#333333"))
    c.rect(margin, y - 13, page_w - 2 * margin, 15, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.drawString(margin + 2, y - 9, "Benämning")
    c.drawString(margin + 95 * mm, y - 9, "Art.nr")
    c.drawRightString(page_w - margin - 4, y - 9, "Antal")
    c.setFillColor(colors.black)
    y -= 17
    c.setFont("Helvetica", 8.5)
    if not p.lines:
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin + 2, y - 8, "Inga artiklar")
        c.setFillColor(colors.black)
        y -= 15
    for l in p.lines:
        y = new_page_if_needed(y, needed=8)
        c.drawString(margin + 2, y - 8, (l.description or "")[:58])
        c.drawString(margin + 95 * mm, y - 8, (l.article_number or (l.article.article_number if l.article else "")) or "–")
        c.drawRightString(page_w - margin - 4, y - 8, f"{float(l.quantity):g} {l.unit}")
        c.setStrokeColor(colors.HexColor("#e5e5e5"))
        c.line(margin, y - 12, page_w - margin, y - 12)
        c.setStrokeColor(colors.black)
        y -= 16
    y -= 14
    return y


@router.get("/{order_id}/purchases/pdf")
def purchases_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(404, "Arbetsorder ej hittad")
    purchases = (
        db.query(Purchase).options(*_LOAD)
        .filter(Purchase.work_order_id == order_id)
        .order_by(Purchase.id)
        .all()
    )

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    subtitle = wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")
    y = draw_header(c, page_w, "Inköp", subtitle)
    y -= 6

    def new_page_if_needed(yy, needed=40):
        if yy < (25 + needed) * mm:
            c.showPage()
            return draw_header(c, page_w, "Inköp", subtitle) - 6
        return yy

    if not purchases:
        c.setFont("Helvetica", 10)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin, y - 12, "Inga inköp registrerade")
        c.setFillColor(colors.black)

    for p in purchases:
        y = _draw_purchase(c, page_w, margin, y, p, new_page_if_needed)

    c.save()
    buf.seek(0)
    filename = f"inkop-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{order_id}/purchases/{purchase_id}/pdf")
def purchase_pdf(
    order_id: int,
    purchase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(404, "Arbetsorder ej hittad")
    p = _get(db, order_id, purchase_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    subtitle = wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")
    y = draw_header(c, page_w, "Inköp", subtitle)
    y -= 6

    def new_page_if_needed(yy, needed=40):
        if yy < (25 + needed) * mm:
            c.showPage()
            return draw_header(c, page_w, "Inköp", subtitle) - 6
        return yy

    _draw_purchase(c, page_w, margin, y, p, new_page_if_needed)

    c.save()
    buf.seek(0)
    filename = f"inkop-{p.purchase_number or p.id}.pdf"
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

import io
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import nulls_last
from sqlalchemy.orm import Session, joinedload
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from ..database import get_db
from ..deps import get_current_user
from ..pdf_utils import draw_header, draw_paragraph, wrap_lines
from ..schemas import (
    WorkOrderCreate, WorkOrderUpdate, WorkOrderOut, WorkOrderListItem,
    WorkOrderLineCreate, WorkOrderLineUpdate, WorkOrderLineOut, WorkOrderLineBulkCreate,
    ScanResult,
)
from ..models import (
    WorkOrder, WorkOrderLine, WorkOrderStatus, Article, StockTransaction,
    StockTransactionType, User, Customer, Vehicle, TimeEntry, Settings, Task,
)

router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

_WO_LOAD = [
    joinedload(WorkOrder.customer),
    joinedload(WorkOrder.vehicle).joinedload(Vehicle.customer),
    joinedload(WorkOrder.assigned_to_user),
    joinedload(WorkOrder.contact_person),
    joinedload(WorkOrder.lines).joinedload(WorkOrderLine.article),
    joinedload(WorkOrder.time_entries).joinedload(TimeEntry.user),
]


def _get_wo(db: Session, order_id: int) -> WorkOrder:
    wo = (
        db.query(WorkOrder)
        .options(*_WO_LOAD)
        .filter(WorkOrder.id == order_id)
        .first()
    )
    if not wo:
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    return wo


def _with_article_number(db: Session, data: dict) -> dict:
    """Snapshotar artikelnumret på raden.

    Raden ska kunna visa sitt art.nr även efter att artikelregistret rensats och
    importerats om (då nollas article_id tillfälligt, se articles._wipe_articles).
    """
    if not data.get("article_number") and data.get("article_id"):
        article = db.get(Article, data["article_id"])
        if article:
            data["article_number"] = article.article_number
    return data


def _next_order_number(db: Session) -> str:
    year = datetime.now().year
    prefix = f"AO-{year}-"
    last = (
        db.query(WorkOrder)
        .filter(WorkOrder.order_number.like(f"{prefix}%"))
        .order_by(WorkOrder.order_number.desc())
        .first()
    )
    if last:
        seq = int(last.order_number.rsplit("-", 1)[-1]) + 1
    else:
        seq = 1
    return f"{prefix}{seq:04d}"


@router.get("", response_model=List[WorkOrderListItem])
def list_work_orders(
    q: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(WorkOrder).options(
        joinedload(WorkOrder.customer),
        joinedload(WorkOrder.vehicle),
        joinedload(WorkOrder.assigned_to_user),
    )
    if q:
        query = query.join(WorkOrder.customer).filter(
            WorkOrder.order_number.ilike(f"%{q}%") |
            Customer.name.ilike(f"%{q}%") |
            WorkOrder.description.ilike(f"%{q}%")
        )
    if status_filter:
        try:
            query = query.filter(WorkOrder.status == WorkOrderStatus(status_filter))
        except ValueError:
            pass
    return query.order_by(WorkOrder.created_at.desc()).all()


@router.post("", response_model=WorkOrderOut, status_code=status.HTTP_201_CREATED)
def create_work_order(
    body: WorkOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(Customer, body.customer_id):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    if body.vehicle_id and not db.get(Vehicle, body.vehicle_id):
        raise HTTPException(status_code=404, detail="Fordon ej hittad")

    data = body.model_dump()
    provided_number = data.pop("order_number", None)
    mode_setting = db.get(Settings, "order_number_mode")
    mode = mode_setting.value if mode_setting else "auto"

    if mode == "manual":
        if not provided_number:
            raise HTTPException(400, "Ordernummer krävs (manuellt läge aktiverat i inställningar)")
        order_number = provided_number
    else:
        order_number = provided_number or _next_order_number(db)

    if db.query(WorkOrder).filter(WorkOrder.order_number == order_number).first():
        raise HTTPException(400, f"Ordernummer {order_number} används redan")

    wo = WorkOrder(order_number=order_number, created_by=current_user.id, **data)
    db.add(wo)
    db.commit()
    return _get_wo(db, wo.id)


@router.get("/calendar", response_model=List[WorkOrderListItem])
def calendar_orders(
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    start = datetime(year, month, 1)
    end = datetime(year, month, last_day, 23, 59, 59)
    return (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.customer), joinedload(WorkOrder.vehicle), joinedload(WorkOrder.assigned_to_user))
        .filter(WorkOrder.scheduled_date >= start, WorkOrder.scheduled_date <= end)
        .order_by(WorkOrder.scheduled_date)
        .all()
    )


@router.get("/{order_id}", response_model=WorkOrderOut)
def get_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return _get_wo(db, order_id)


@router.put("/{order_id}", response_model=WorkOrderOut)
def update_work_order(
    order_id: int,
    body: WorkOrderUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    data = body.model_dump(exclude_unset=True)
    if "status" in data:
        if data["status"] == WorkOrderStatus.pagaende and not wo.started_at:
            wo.started_at = datetime.utcnow()
        if data["status"] == WorkOrderStatus.klar and not wo.completed_at:
            wo.completed_at = datetime.utcnow()
    for field, value in data.items():
        setattr(wo, field, value)
    db.commit()
    return _get_wo(db, order_id)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    # Lagertransaktioner refererar ordern utan cascade – behåll historiken men släpp kopplingen
    db.query(StockTransaction).filter(StockTransaction.work_order_id == order_id).update(
        {StockTransaction.work_order_id: None}, synchronize_session=False
    )
    db.delete(wo)
    db.commit()


# ── Lines ─────────────────────────────────────────────────────────────────────

@router.get("/{order_id}/lines", response_model=List[WorkOrderLineOut])
def list_lines(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(WorkOrderLine)
        .options(joinedload(WorkOrderLine.article))
        .filter(WorkOrderLine.work_order_id == order_id)
        .order_by(WorkOrderLine.id)
        .all()
    )


@router.post("/{order_id}/lines", response_model=WorkOrderLineOut, status_code=status.HTTP_201_CREATED)
def add_line(
    order_id: int,
    body: WorkOrderLineCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    line = WorkOrderLine(work_order_id=order_id, **_with_article_number(db, body.model_dump()))
    db.add(line)
    db.commit()
    db.refresh(line)
    return (
        db.query(WorkOrderLine)
        .options(joinedload(WorkOrderLine.article))
        .get(line.id)
    )


@router.post("/{order_id}/lines/bulk", response_model=List[WorkOrderLineOut], status_code=status.HTTP_201_CREATED)
def add_lines_bulk(
    order_id: int,
    body: WorkOrderLineBulkCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    created_ids = []
    for line in body.lines:
        wl = WorkOrderLine(work_order_id=order_id, **_with_article_number(db, line.model_dump()))
        db.add(wl)
        db.flush()
        created_ids.append(wl.id)
    db.commit()
    return (
        db.query(WorkOrderLine)
        .options(joinedload(WorkOrderLine.article))
        .filter(WorkOrderLine.id.in_(created_ids))
        .order_by(WorkOrderLine.id)
        .all()
    )


@router.put("/{order_id}/lines/{line_id}", response_model=WorkOrderLineOut)
def update_line(
    order_id: int,
    line_id: int,
    body: WorkOrderLineUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    line = db.query(WorkOrderLine).filter(
        WorkOrderLine.id == line_id, WorkOrderLine.work_order_id == order_id
    ).first()
    if not line:
        raise HTTPException(status_code=404, detail="Rad ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(line, field, value)
    db.commit()
    return (
        db.query(WorkOrderLine)
        .options(joinedload(WorkOrderLine.article))
        .get(line_id)
    )


@router.delete("/{order_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(
    order_id: int,
    line_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    line = db.query(WorkOrderLine).filter(
        WorkOrderLine.id == line_id, WorkOrderLine.work_order_id == order_id
    ).first()
    if not line:
        raise HTTPException(status_code=404, detail="Rad ej hittad")
    db.delete(line)
    db.commit()


# ── Scanner ───────────────────────────────────────────────────────────────────

@router.post("/{order_id}/scan", response_model=ScanResult)
def scan_article(
    order_id: int,
    barcode: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    wo = db.get(WorkOrder, order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")

    article = db.query(Article).filter(
        (Article.barcode == barcode) | (Article.article_number == barcode)
    ).first()

    if article:
        # Known article — find or create line, deduct stock
        line = db.query(WorkOrderLine).filter(
            WorkOrderLine.work_order_id == order_id,
            WorkOrderLine.article_id == article.id,
        ).first()
        if line:
            line.quantity = line.quantity + Decimal("1")
            if not line.article_number:
                line.article_number = article.article_number
        else:
            line = WorkOrderLine(
                work_order_id=order_id,
                article_id=article.id,
                article_number=article.article_number,
                description=article.name,
                quantity=Decimal("1"),
                unit=article.unit,
                unit_price=article.price,
            )
            db.add(line)
        article.stock_quantity = article.stock_quantity - Decimal("1")
        tx = StockTransaction(
            article_id=article.id,
            quantity=Decimal("-1"),
            transaction_type=StockTransactionType.out,
            work_order_id=order_id,
            user_id=current_user.id,
            notes=f"Plockad till {wo.order_number}",
        )
        db.add(tx)
        db.commit()
        db.refresh(line)
        db.refresh(article)
        line_with_article = (
            db.query(WorkOrderLine)
            .options(joinedload(WorkOrderLine.article))
            .get(line.id)
        )
        return ScanResult(
            article=article,
            article_name=article.name,
            line=line_with_article,
            stock_warning=article.stock_quantity < article.min_stock,
            stock_quantity=article.stock_quantity,
            unknown=False,
        )
    else:
        # Unknown barcode — add as unnamed line, no article record created
        desc = f"Okänd ({barcode})"
        line = db.query(WorkOrderLine).filter(
            WorkOrderLine.work_order_id == order_id,
            WorkOrderLine.article_id.is_(None),
            WorkOrderLine.description == desc,
        ).first()
        if line:
            line.quantity = line.quantity + Decimal("1")
        else:
            line = WorkOrderLine(
                work_order_id=order_id,
                article_id=None,
                # Den skannade koden sparas som art.nr – då hittar raden tillbaka
                # till artikeln om den dyker upp vid en senare import
                article_number=barcode,
                description=desc,
                quantity=Decimal("1"),
                unit="st",
                unit_price=Decimal("0"),
            )
            db.add(line)
        db.commit()
        db.refresh(line)
        return ScanResult(
            article=None,
            article_name=desc,
            line=line,
            stock_warning=False,
            stock_quantity=None,
            unknown=True,
        )


# ── Invoice basis (PDF) ───────────────────────────────────────────────────────

def _line_art_nr(line: WorkOrderLine) -> str:
    """Radens sparade art.nr, med artikelregistret som fallback för äldre rader."""
    return line.article_number or (line.article.article_number if line.article else "") or ""


def _fmt_minutes(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"


@router.get("/{order_id}/invoice")
def invoice_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = _get_wo(db, order_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    subtitle = wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")
    y = draw_header(c, page_w, "Fakturaunderlag", subtitle)

    # ── Meta block ──
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#444444"))
    veh = ""
    if wo.vehicle:
        veh = f"{wo.vehicle.license_plate} {wo.vehicle.make or ''} {wo.vehicle.model or ''}".strip()
    meta = [
        ("Kund", wo.customer.name if wo.customer else "–"),
        ("Kontakt", wo.contact_person.name if wo.contact_person else "–"),
        ("Fordon", veh or "–"),
        ("Ärende", (wo.description or "")[:110]),
    ]
    for label, value in meta:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, f"{label}:")
        c.setFont("Helvetica", 9)
        c.drawString(margin + 24 * mm, y, str(value))
        y -= 13
    c.setFillColor(colors.black)
    y -= 8

    def section_title(yy, text):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin, yy, text)
        return yy - 6

    def table_header(yy, cols):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#1a1a1a"))
        c.rect(margin, yy - 14, page_w - 2 * margin, 16, fill=1, stroke=0)
        c.setFillColor(colors.white)
        for x, label in cols:
            c.drawString(x, yy - 10, label)
        c.setFillColor(colors.black)
        return yy - 18

    def page_break_if_needed(yy):
        if yy < 30 * mm:
            c.showPage()
            yy = draw_header(c, page_w, "Fakturaunderlag", subtitle) - 6
        return yy

    # ── Reservdelar ──
    y = section_title(y, "Reservdelar")
    cols = [(margin + 2, "Artikel"), (margin + 95 * mm, "Art.nr"), (page_w - margin - 30 * mm, "Antal")]
    y = table_header(y, cols)
    c.setFont("Helvetica", 8.5)
    if not wo.lines:
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin + 2, y - 8, "Inga reservdelar")
        c.setFillColor(colors.black)
        y -= 16
    for l in wo.lines:
        y = page_break_if_needed(y)
        c.drawString(margin + 2, y - 8, (l.description or "")[:60])
        c.drawString(margin + 95 * mm, y - 8, _line_art_nr(l) or "–")
        c.drawRightString(page_w - margin - 4, y - 8, f"{float(l.quantity):g} {l.unit}")
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y - 12, page_w - margin, y - 12)
        c.setStrokeColor(colors.black)
        y -= 16

    y -= 12
    y = page_break_if_needed(y)

    # ── Arbetstid ──
    y = section_title(y, "Arbetstid")
    cols = [(margin + 2, "Tekniker"), (margin + 70 * mm, "Typ"), (page_w - margin - 30 * mm, "Tid")]
    y = table_header(y, cols)
    c.setFont("Helvetica", 8.5)
    total_minutes = 0
    done_entries = [e for e in wo.time_entries if e.end_time]
    if not done_entries:
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin + 2, y - 8, "Ingen registrerad tid")
        c.setFillColor(colors.black)
        y -= 16
    for e in done_entries:
        y = page_break_if_needed(y)
        total_minutes += e.duration_minutes or 0
        c.drawString(margin + 2, y - 8, (e.user.full_name if e.user else "")[:40])
        c.drawString(margin + 70 * mm, y - 8, e.entry_type.value if e.entry_type else "")
        c.drawRightString(page_w - margin - 4, y - 8, _fmt_minutes(e.duration_minutes))
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y - 12, page_w - margin, y - 12)
        c.setStrokeColor(colors.black)
        y -= 16

    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(margin + 2, y - 10, "Total tid")
    c.drawRightString(page_w - margin - 4, y - 10, _fmt_minutes(total_minutes))

    c.save()
    buf.seek(0)
    filename = f"fakturaunderlag-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Parts (reservdelar) PDF ───────────────────────────────────────────────────

@router.get("/{order_id}/parts/pdf")
def parts_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = _get_wo(db, order_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    subtitle = wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")
    y = draw_header(c, page_w, "Reservdelar", subtitle)
    y -= 6

    def new_page_if_needed(yy, needed=40):
        if yy < (25 + needed) * mm:
            c.showPage()
            return draw_header(c, page_w, "Reservdelar", subtitle) - 6
        return yy

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(colors.HexColor("#1a1a1a"))
    c.rect(margin, y - 14, page_w - 2 * margin, 16, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.drawString(margin + 2, y - 10, "Artikel")
    c.drawString(margin + 95 * mm, y - 10, "Art.nr")
    c.drawRightString(page_w - margin - 4, y - 10, "Antal")
    c.setFillColor(colors.black)
    y -= 18

    c.setFont("Helvetica", 8.5)
    if not wo.lines:
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin + 2, y - 8, "Inga reservdelar")
        c.setFillColor(colors.black)
        y -= 16
    for l in wo.lines:
        y = new_page_if_needed(y, needed=8)
        c.drawString(margin + 2, y - 8, (l.description or "")[:60])
        c.drawString(margin + 95 * mm, y - 8, _line_art_nr(l) or "–")
        c.drawRightString(page_w - margin - 4, y - 8, f"{float(l.quantity):g} {l.unit}")
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y - 12, page_w - margin, y - 12)
        c.setStrokeColor(colors.black)
        y -= 16

    c.save()
    buf.seek(0)
    filename = f"reservdelar-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Arbetstext (PDF) ──────────────────────────────────────────────────────────

def _wo_subtitle(wo: WorkOrder) -> str:
    return wo.order_number + (f" – {wo.customer.name}" if wo.customer else "")


def _draw_meta(c, wo: WorkOrder, y, margin, label_w=24 * mm):
    """Kund/fordon/ansvarig-block som inledning på en utskrift."""
    veh = ""
    if wo.vehicle:
        veh = f"{wo.vehicle.license_plate} {wo.vehicle.make or ''} {wo.vehicle.model or ''}".strip()
    meta = [
        ("Kund", wo.customer.name if wo.customer else "–"),
        ("Kontakt", wo.contact_person.name if wo.contact_person else "–"),
        ("Fordon", veh or "–"),
        ("Ansvarig", wo.assigned_to_user.full_name if wo.assigned_to_user else "–"),
        ("Ärende", (wo.description or "")[:110]),
    ]
    for label, value in meta:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(margin, y, f"{label}:")
        c.setFont("Helvetica", 9)
        c.drawString(margin + label_w, y, str(value))
        y -= 13
    return y - 8


@router.get("/{order_id}/bodytext/pdf")
def body_text_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = _get_wo(db, order_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm
    subtitle = _wo_subtitle(wo)

    y = draw_header(c, page_w, "Arbetstext", subtitle)
    y = _draw_meta(c, wo, y, margin)

    c.setStrokeColor(colors.HexColor("#dddddd"))
    c.line(margin, y, page_w - margin, y)
    c.setStrokeColor(colors.black)
    y -= 16

    text = (wo.body_text or "").strip()
    if text:
        y = draw_paragraph(
            c, text, margin, y, page_w - 2 * margin,
            font_size=10, leading=14, min_y=22 * mm,
            on_new_page=lambda: draw_header(c, page_w, "Arbetstext", subtitle) - 6,
        )
    else:
        c.setFont("Helvetica-Oblique", 10)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin, y, "Ingen arbetstext registrerad")
        c.setFillColor(colors.black)

    c.save()
    buf.seek(0)
    filename = f"arbetstext-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Uppgifter (PDF) ───────────────────────────────────────────────────────────

@router.get("/{order_id}/tasks/pdf")
def tasks_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = _get_wo(db, order_id)
    tasks = (
        db.query(Task)
        .options(joinedload(Task.assigned_user))
        .filter(Task.work_order_id == order_id)
        .order_by(Task.completed, nulls_last(Task.due_date), Task.id)
        .all()
    )

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm
    subtitle = _wo_subtitle(wo)

    y = draw_header(c, page_w, "Uppgifter", subtitle)
    y = _draw_meta(c, wo, y, margin)

    done = sum(1 for t in tasks if t.completed)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, y, f"{done} av {len(tasks)} uppgifter klara")
    c.setFillColor(colors.black)
    y -= 18

    col_assignee = page_w - margin - 62 * mm
    col_due = page_w - margin - 24 * mm

    def header_row(yy):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#1a1a1a"))
        c.rect(margin, yy - 14, page_w - 2 * margin, 16, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.drawString(margin + 14, yy - 10, "Uppgift")
        c.drawString(col_assignee, yy - 10, "Ansvarig")
        c.drawString(col_due, yy - 10, "Förfaller")
        c.setFillColor(colors.black)
        return yy - 20

    y = header_row(y)

    if not tasks:
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(colors.HexColor("#888888"))
        c.drawString(margin + 2, y - 6, "Inga uppgifter registrerade")
        c.setFillColor(colors.black)

    title_width = col_assignee - margin - 18
    for t in tasks:
        title_lines = wrap_lines(t.title or "", "Helvetica-Bold", 9.5, title_width)
        desc_lines = wrap_lines(t.description or "", "Helvetica", 8.5, title_width) if t.description else []
        row_h = max(18, 13 * len(title_lines) + 11 * len(desc_lines) + 6)

        if y - row_h < 22 * mm:
            c.showPage()
            y = draw_header(c, page_w, "Uppgifter", subtitle) - 6
            y = header_row(y)

        # Kryssruta – ifylld när uppgiften är klar
        c.setLineWidth(0.8)
        c.setStrokeColor(colors.HexColor("#999999"))
        c.rect(margin + 1, y - 11, 9, 9, stroke=1, fill=0)
        if t.completed:
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin + 2.5, y - 10, "X")
        c.setStrokeColor(colors.black)

        ty = y
        for i, line in enumerate(title_lines):
            c.setFont("Helvetica-Bold", 9.5)
            c.setFillColor(colors.HexColor("#888888") if t.completed else colors.black)
            c.drawString(margin + 16, ty - 9, line)
            if i == 0:
                c.setFont("Helvetica", 8.5)
                c.setFillColor(colors.HexColor("#444444"))
                c.drawString(col_assignee, ty - 9, (t.assigned_user.full_name if t.assigned_user else "–")[:22])
                c.drawString(col_due, ty - 9, t.due_date.strftime("%Y-%m-%d") if t.due_date else "–")
            ty -= 13
        c.setFillColor(colors.HexColor("#666666"))
        for line in desc_lines:
            c.setFont("Helvetica", 8.5)
            c.drawString(margin + 16, ty - 8, line)
            ty -= 11
        c.setFillColor(colors.black)

        y -= row_h
        c.setStrokeColor(colors.HexColor("#e5e5e5"))
        c.line(margin, y + 4, page_w - margin, y + 4)
        c.setStrokeColor(colors.black)

    c.save()
    buf.seek(0)
    filename = f"uppgifter-{wo.order_number}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

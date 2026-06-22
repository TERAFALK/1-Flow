from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..deps import get_current_user
from ..schemas import (
    WorkOrderCreate, WorkOrderUpdate, WorkOrderOut, WorkOrderListItem,
    WorkOrderLineCreate, WorkOrderLineUpdate, WorkOrderLineOut, ScanResult,
)
from ..models import (
    WorkOrder, WorkOrderLine, WorkOrderStatus, Article, StockTransaction,
    StockTransactionType, User, Customer, Vehicle, TimeEntry, Settings,
)

router = APIRouter(prefix="/api/work-orders", tags=["work-orders"])

_WO_LOAD = [
    joinedload(WorkOrder.customer),
    joinedload(WorkOrder.vehicle).joinedload(Vehicle.customer),
    joinedload(WorkOrder.assigned_to_user),
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
    data = body.model_dump(exclude_none=True)
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
    line = WorkOrderLine(work_order_id=order_id, **body.model_dump())
    db.add(line)
    db.commit()
    db.refresh(line)
    return (
        db.query(WorkOrderLine)
        .options(joinedload(WorkOrderLine.article))
        .get(line.id)
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
    for field, value in body.model_dump(exclude_none=True).items():
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
        else:
            line = WorkOrderLine(
                work_order_id=order_id,
                article_id=article.id,
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


# ── Invoice basis ─────────────────────────────────────────────────────────────

@router.get("/{order_id}/invoice")
def invoice_basis(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    wo = _get_wo(db, order_id)
    lines = [
        {
            "id": l.id,
            "description": l.description,
            "quantity": float(l.quantity),
            "unit": l.unit,
            "unit_price": float(l.unit_price),
            "total": float(l.quantity * l.unit_price),
            "article_number": l.article.article_number if l.article else None,
        }
        for l in wo.lines
    ]
    total_minutes = sum(
        (e.duration_minutes or 0) for e in wo.time_entries if e.end_time
    )
    parts_total = sum(l["total"] for l in lines)
    return {
        "order_number": wo.order_number,
        "customer": {"id": wo.customer.id, "name": wo.customer.name} if wo.customer else None,
        "vehicle": {
            "license_plate": wo.vehicle.license_plate,
            "make": wo.vehicle.make,
            "model": wo.vehicle.model,
        } if wo.vehicle else None,
        "description": wo.description,
        "lines": lines,
        "parts_total": parts_total,
        "labor_minutes": total_minutes,
        "labor_hours": round(total_minutes / 60, 2),
        "time_entries": [
            {
                "user": e.user.full_name if e.user else "",
                "start": e.start_time.isoformat() if e.start_time else None,
                "end": e.end_time.isoformat() if e.end_time else None,
                "minutes": e.duration_minutes,
                "description": e.description,
                "type": e.entry_type.value if e.entry_type else "",
            }
            for e in wo.time_entries
        ],
        "status": wo.status.value,
    }

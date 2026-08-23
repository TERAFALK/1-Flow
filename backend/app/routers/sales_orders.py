from datetime import date
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, extract, func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import (
    SalesOrder, SalesOrderMilestone, SalesMilestoneDef, SalesLead,
    Customer, User,
)
from ..schemas import (
    SalesOrderCreate, SalesOrderUpdate, SalesOrderOut, SalesOrderListItem,
    SalesOrderMilestoneOut, SalesOrderMilestoneUpdate,
    SalesCommissionRow, SalesCommissionSummary,
)

router = APIRouter(prefix="/api/sales/orders", tags=["sales-orders"])


def _get(db: Session, order_id: int) -> SalesOrder:
    order = (
        db.query(SalesOrder)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.milestones).joinedload(SalesOrderMilestone.definition),
        )
        .filter(SalesOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order ej hittad")
    return order


def _is_done(m: SalesOrderMilestone) -> bool:
    """En milstolpe räknas som klar när den fått ett värde – oavsett om det är ett
    datum, en fritext eller en ikryssad ruta. Speglar hur cellerna används i Excel."""
    return bool(m.completed or m.value_date or (m.value_text or "").strip())


def _list_fields(order: SalesOrder) -> dict:
    active = [m for m in order.milestones if m.definition and m.definition.is_active]
    return dict(
        id=order.id,
        lead_id=order.lead_id,
        customer_id=order.customer_id,
        customer_name=order.customer.name if order.customer else "",
        order_number=order.order_number,
        serial_number=order.serial_number,
        product_type=order.product_type,
        price=order.price,
        currency=order.currency,
        commission=order.commission,
        commission_paid_date=order.commission_paid_date,
        sold_date=order.sold_date,
        delivery_date=order.delivery_date,
        planned_delivery=order.planned_delivery,
        delivery_week=order.delivery_week,
        registration_number=order.registration_number,
        weight_kg=order.weight_kg,
        visit_ffb=order.visit_ffb,
        sort_index=order.sort_index,
        milestones_done=sum(1 for m in active if _is_done(m)),
        milestones_total=len(active),
    )


def _milestone_out(m: SalesOrderMilestone) -> SalesOrderMilestoneOut:
    d = m.definition
    return SalesOrderMilestoneOut(
        def_id=d.id,
        key=d.key,
        group_label=d.group_label,
        label=d.label,
        value_type=d.value_type,
        sort_order=d.sort_order,
        value_date=m.value_date,
        value_text=m.value_text,
        completed=_is_done(m),
        updated_at=m.updated_at,
    )


def order_out(db: Session, order_id: int) -> SalesOrderOut:
    """Delad av den här modulen och av lead-konverteringen i sales_leads.py."""
    order = _get(db, order_id)
    _ensure_milestones(db, order)
    milestones = [m for m in order.milestones if m.definition and m.definition.is_active]
    milestones.sort(key=lambda m: (m.definition.sort_order, m.definition.id))
    return SalesOrderOut(
        **_list_fields(order),
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
        milestones=[_milestone_out(m) for m in milestones],
    )


def _ensure_milestones(db: Session, order: SalesOrder) -> None:
    """Skapar rader för milstolpar som lagts till efter att ordern skapades, så att
    en ny milstolpe i mallen dyker upp på alla befintliga ordrar."""
    have = {m.def_id for m in order.milestones}
    missing = (
        db.query(SalesMilestoneDef)
        .filter(SalesMilestoneDef.is_active.is_(True), ~SalesMilestoneDef.id.in_(have or [0]))
        .all()
    )
    if not missing:
        return
    for definition in missing:
        db.add(SalesOrderMilestone(order_id=order.id, def_id=definition.id))
    db.commit()
    db.refresh(order)


# ── Ordrar ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SalesOrderListItem])
def list_orders(
    year: Optional[int] = None,
    q: Optional[str] = None,
    customer_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = (
        db.query(SalesOrder)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.milestones).joinedload(SalesOrderMilestone.definition),
        )
    )
    if year:
        query = query.filter(extract("year", SalesOrder.sold_date) == year)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Customer.name.ilike(like),
            SalesOrder.order_number.ilike(like),
            SalesOrder.serial_number.ilike(like),
            SalesOrder.product_type.ilike(like),
            SalesOrder.registration_number.ilike(like),
        ))
    if customer_id:
        query = query.filter(SalesOrder.customer_id == customer_id)
    orders = query.order_by(
        SalesOrder.sold_date.desc().nullslast(), SalesOrder.id.desc()
    ).all()
    return [SalesOrderListItem(**_list_fields(o)) for o in orders]


@router.get("/years", response_model=List[int])
def list_years(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = (
        db.query(extract("year", SalesOrder.sold_date))
        .filter(SalesOrder.sold_date.isnot(None))
        .distinct()
        .all()
    )
    return sorted({int(r[0]) for r in rows}, reverse=True)


@router.get("/commission", response_model=SalesCommissionSummary)
def commission_summary(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Ersätter fliken 'Kommission' – provision per order plus årssumma."""
    query = db.query(SalesOrder).options(joinedload(SalesOrder.customer))
    if year:
        query = query.filter(extract("year", SalesOrder.sold_date) == year)
    orders = query.order_by(SalesOrder.sold_date.asc().nullslast(), SalesOrder.id.asc()).all()

    rows = [
        SalesCommissionRow(
            order_id=o.id,
            order_number=o.order_number,
            customer_name=o.customer.name if o.customer else "",
            product_type=o.product_type,
            sold_date=o.sold_date,
            price=o.price,
            commission=o.commission,
            commission_paid_date=o.commission_paid_date,
        )
        for o in orders
    ]
    zero = Decimal("0")
    return SalesCommissionSummary(
        year=year,
        rows=rows,
        total_price=sum((o.price or zero for o in orders), zero),
        total_commission=sum((o.commission or zero for o in orders), zero),
        paid_commission=sum((o.commission or zero for o in orders if o.commission_paid_date), zero),
        unpaid_commission=sum((o.commission or zero for o in orders if not o.commission_paid_date), zero),
    )


@router.post("", response_model=SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: SalesOrderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(Customer, body.customer_id):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    if body.lead_id is not None:
        if not db.get(SalesLead, body.lead_id):
            raise HTTPException(status_code=404, detail="Förfrågan ej hittad")
        if db.query(SalesOrder.id).filter(SalesOrder.lead_id == body.lead_id).first():
            raise HTTPException(status_code=400, detail="Förfrågan har redan en order")
    order = SalesOrder(**body.model_dump())
    db.add(order)
    db.commit()
    return order_out(db, order.id)


@router.get("/{order_id}", response_model=SalesOrderOut)
def get_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return order_out(db, order_id)


@router.put("/{order_id}", response_model=SalesOrderOut)
def update_order(
    order_id: int,
    body: SalesOrderUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get(db, order_id)
    fields = body.model_dump(exclude_unset=True)
    if fields.get("customer_id") and not db.get(Customer, fields["customer_id"]):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    for field, value in fields.items():
        setattr(order, field, value)
    db.commit()
    return order_out(db, order_id)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    order = _get(db, order_id)
    db.delete(order)
    db.commit()


# ── Milstolpar ────────────────────────────────────────────────────────────────

@router.get("/{order_id}/milestones", response_model=List[SalesOrderMilestoneOut])
def list_milestones(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return order_out(db, order_id).milestones


@router.put("/{order_id}/milestones/{def_id}", response_model=SalesOrderMilestoneOut)
def set_milestone(
    order_id: int,
    def_id: int,
    body: SalesOrderMilestoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, order_id)
    if not db.get(SalesMilestoneDef, def_id):
        raise HTTPException(status_code=404, detail="Milstolpe ej hittad")

    milestone = db.query(SalesOrderMilestone).filter(
        SalesOrderMilestone.order_id == order_id,
        SalesOrderMilestone.def_id == def_id,
    ).first()
    if not milestone:
        milestone = SalesOrderMilestone(order_id=order_id, def_id=def_id)
        db.add(milestone)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    milestone.updated_by = current_user.id
    db.commit()
    db.refresh(milestone)
    return _milestone_out(milestone)

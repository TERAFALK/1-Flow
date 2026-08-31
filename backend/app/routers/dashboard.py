from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..schemas import (
    DashboardStats, WorkOrderListItem, ActiveTimer,
    SalesAreaSummary, UpcomingItem, MonthlySalesPoint,
)
from ..models import (
    WorkOrder, WorkOrderStatus, Task, TimeEntry, User,
    SalesLead, SalesLeadKind, SalesLeadStatus, SalesOrder,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# Statusar där affären fortfarande är i spel – samma som i sales_leads.py
OPEN_LEAD_STATUSES = (SalesLeadStatus.ny, SalesLeadStatus.skickad, SalesLeadStatus.jobbar)
OPEN_ORDER_STATUSES = (WorkOrderStatus.ny, WorkOrderStatus.planerad, WorkOrderStatus.pagaende)

UPCOMING_DAYS = 30
MONTHS_BACK = 12

AREAS = [
    (SalesLeadKind.feldbinder, "Feldbinder", "/sales", "EUR"),
    (SalesLeadKind.verkstad, "Offerter", "/quotes", "SEK"),
]


def _month_key(value) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _last_months(n: int) -> List[str]:
    """De n senaste månaderna, äldst först. Räknas bakåt från den första i
    innevarande månad så att månadslängder inte spelar någon roll."""
    cursor = date.today().replace(day=1)
    months = []
    for _ in range(n):
        months.append(_month_key(cursor))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    return list(reversed(months))


# ── Delfrågor ─────────────────────────────────────────────────────────────────

def _workshop(db: Session, today: date) -> dict:
    counts = dict(
        db.query(WorkOrder.status, func.count(WorkOrder.id))
        .group_by(WorkOrder.status)
        .all()
    )
    by_status = {s.value: counts.get(s, 0) for s in WorkOrderStatus}

    day_start = datetime.combine(today, datetime.min.time())
    day_end = datetime.combine(today, datetime.max.time())
    scheduled_today = (
        db.query(func.count(WorkOrder.id))
        .filter(WorkOrder.scheduled_date >= day_start, WorkOrder.scheduled_date <= day_end)
        .scalar()
    )

    # Innevarande vecka räknas från måndag, som resten av verkstadens planering
    week_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    completed_this_week = (
        db.query(func.count(WorkOrder.id))
        .filter(WorkOrder.completed_at >= week_start)
        .scalar()
    )

    return dict(
        by_status=by_status,
        total_open=sum(by_status[s.value] for s in OPEN_ORDER_STATUSES),
        scheduled_today=scheduled_today or 0,
        ready_to_invoice=by_status[WorkOrderStatus.klar.value],
        completed_this_week=completed_this_week or 0,
    )


def _active_timers(db: Session) -> List[ActiveTimer]:
    rows = (
        db.query(TimeEntry)
        .options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order))
        .filter(TimeEntry.end_time.is_(None))
        .order_by(TimeEntry.start_time)
        .all()
    )
    return [
        ActiveTimer(
            user_name=t.user.full_name if t.user else "–",
            order_id=t.work_order_id,
            order_number=t.work_order.order_number if t.work_order else "",
            started_at=t.start_time,
        )
        for t in rows
    ]


def _overdue_tasks(db: Session, today: date) -> int:
    """Förfallna uppgifter på både arbetsorder och offerter."""
    return (
        db.query(func.count(Task.id))
        .filter(
            Task.due_date < datetime.combine(today, datetime.min.time()),
            Task.completed.is_(False),
        )
        .scalar()
    ) or 0


def _sales(db: Session, today: date) -> List[SalesAreaSummary]:
    year_start = date(today.year, 1, 1)
    zero = Decimal("0")
    result = []

    for kind, label, route, currency in AREAS:
        def scoped(query):
            return query.filter(SalesLead.kind == kind, SalesLead.archived_at.is_(None))

        open_leads = scoped(
            db.query(func.count(SalesLead.id)).filter(SalesLead.status.in_(OPEN_LEAD_STATUSES))
        ).scalar() or 0
        open_value = scoped(
            db.query(func.coalesce(func.sum(SalesLead.estimated_value), 0))
            .filter(SalesLead.status.in_(OPEN_LEAD_STATUSES))
        ).scalar() or zero
        overdue = scoped(
            db.query(func.count(SalesLead.id)).filter(
                SalesLead.next_followup_date <= today,
                SalesLead.status.in_(OPEN_LEAD_STATUSES),
            )
        ).scalar() or 0

        if kind == SalesLeadKind.feldbinder:
            # Feldbinder-affärer blir en SalesOrder – där finns både sålddatum och
            # pris. Arkiverade räknas med: årets försäljning ändras inte av städning.
            sold = (
                db.query(func.count(SalesOrder.id), func.coalesce(func.sum(SalesOrder.price), 0))
                .filter(SalesOrder.sold_date >= year_start)
                .first()
            )
            sold_count, sold_value = (sold[0] or 0, sold[1] or zero)
            unpaid = (
                db.query(func.coalesce(func.sum(SalesOrder.commission), 0))
                .filter(SalesOrder.commission_paid_date.is_(None))
                .scalar()
            ) or zero
            extra_label, extra_value = "Ej utbetald provision", f"{unpaid:,.0f} EUR".replace(",", " ")
        else:
            # En verkstadsoffert har inget eget sålddatum – arbetsordern som skapades
            # är den riktiga affärshändelsen, med lead.updated_at som reserv.
            rows = (
                db.query(SalesLead)
                .outerjoin(WorkOrder, SalesLead.work_order_id == WorkOrder.id)
                .filter(SalesLead.kind == kind, SalesLead.status == SalesLeadStatus.sald)
                .all()
            )
            sold_count, sold_value, became = 0, zero, 0
            for lead in rows:
                when = lead.work_order.created_at if lead.work_order else lead.updated_at
                if when and when.date() >= year_start:
                    sold_count += 1
                    sold_value += lead.estimated_value or zero
                if lead.work_order_id:
                    became += 1
            extra_label, extra_value = "Blivit arbetsorder", str(became)

        result.append(SalesAreaSummary(
            kind=kind.value, label=label, route=route, currency=currency,
            open_leads=open_leads, open_value=open_value, overdue_followups=overdue,
            sold_ytd_count=sold_count, sold_ytd_value=sold_value,
            extra_label=extra_label, extra_value=extra_value,
        ))
    return result


def _upcoming(db: Session, today: date) -> List[UpcomingItem]:
    horizon = today + timedelta(days=UPCOMING_DAYS)
    items: List[UpcomingItem] = []

    # Planerade FFB-leveranser som ännu inte levererats
    orders = (
        db.query(SalesOrder)
        .options(joinedload(SalesOrder.customer))
        .filter(
            SalesOrder.planned_delivery.isnot(None),
            SalesOrder.planned_delivery <= horizon,
            SalesOrder.delivery_date.is_(None),
            SalesOrder.archived_at.is_(None),
        )
        .all()
    )
    for o in orders:
        items.append(UpcomingItem(
            date=o.planned_delivery,
            kind="leverans",
            label=o.order_number or f"Order #{o.id}",
            sub=" · ".join(x for x in [o.customer.name if o.customer else None, o.product_type] if x),
            link=f"#/sales-orders/{o.id}",
            overdue=o.planned_delivery < today,
        ))

    # Schemalagda arbetsorder som inte är avslutade
    wos = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.customer))
        .filter(
            WorkOrder.scheduled_date.isnot(None),
            WorkOrder.scheduled_date <= datetime.combine(horizon, datetime.max.time()),
            WorkOrder.status.in_(OPEN_ORDER_STATUSES),
        )
        .all()
    )
    for w in wos:
        when = w.scheduled_date.date()
        items.append(UpcomingItem(
            date=when,
            kind="arbetsorder",
            label=w.order_number,
            sub=w.customer.name if w.customer else None,
            link=f"#/work-orders/{w.id}",
            overdue=when < today,
        ))

    # Försenat först, därefter kronologiskt
    items.sort(key=lambda i: i.date)
    return items[:20]


def _monthly_sales(db: Session) -> List[MonthlySalesPoint]:
    months = _last_months(MONTHS_BACK)
    buckets = {m: {"feldbinder": Decimal("0"), "verkstad": Decimal("0")} for m in months}

    for order in db.query(SalesOrder).filter(SalesOrder.sold_date.isnot(None)).all():
        key = _month_key(order.sold_date)
        if key in buckets:
            buckets[key]["feldbinder"] += order.price or Decimal("0")

    sold_leads = (
        db.query(SalesLead)
        .filter(
            SalesLead.kind == SalesLeadKind.verkstad,
            SalesLead.status == SalesLeadStatus.sald,
        )
        .all()
    )
    for lead in sold_leads:
        when = lead.work_order.created_at if lead.work_order else lead.updated_at
        if not when:
            continue
        key = _month_key(when)
        if key in buckets:
            buckets[key]["verkstad"] += lead.estimated_value or Decimal("0")

    return [MonthlySalesPoint(month=m, **buckets[m]) for m in months]


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("", response_model=DashboardStats)
def dashboard(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Allt i ett anrop – sidan laddar ändå bara en gång, och det håller
    dashboard.js fri från sex parallella hämtningar."""
    today = date.today()

    # Åtgärdsraden visar båda delarnas passerade uppföljningar tillsammans
    sales = _sales(db, today)
    overdue_followups = sum(a.overdue_followups for a in sales)

    recent = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.customer),
            joinedload(WorkOrder.vehicle),
            joinedload(WorkOrder.assigned_to_user),
        )
        .order_by(WorkOrder.created_at.desc())
        .limit(8)
        .all()
    )

    return DashboardStats(
        **_workshop(db, today),
        overdue_followups=overdue_followups,
        overdue_tasks=_overdue_tasks(db, today),
        active_timers=_active_timers(db),
        sales=sales,
        monthly_sales=_monthly_sales(db),
        upcoming=_upcoming(db, today),
        recent_orders=[WorkOrderListItem.model_validate(o) for o in recent],
    )

from datetime import datetime, date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..deps import get_current_user
from ..schemas import DashboardStats, WorkOrderListItem
from ..models import WorkOrder, WorkOrderStatus, User, Vehicle

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardStats)
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())

    by_status = {}
    for s in WorkOrderStatus:
        by_status[s.value] = db.query(WorkOrder).filter(WorkOrder.status == s).count()

    open_statuses = [WorkOrderStatus.ny, WorkOrderStatus.planerad, WorkOrderStatus.pagaende]
    total_open = sum(by_status[s.value] for s in open_statuses)

    scheduled_today = db.query(WorkOrder).filter(
        WorkOrder.scheduled_date >= today_start,
        WorkOrder.scheduled_date <= today_end,
    ).count()

    ready_to_invoice = by_status[WorkOrderStatus.klar.value]

    recent = (
        db.query(WorkOrder)
        .options(
            joinedload(WorkOrder.customer),
            joinedload(WorkOrder.vehicle),
            joinedload(WorkOrder.assigned_to_user),
        )
        .order_by(WorkOrder.created_at.desc())
        .limit(10)
        .all()
    )

    return DashboardStats(
        total_open=total_open,
        by_status=by_status,
        scheduled_today=scheduled_today,
        ready_to_invoice=ready_to_invoice,
        recent_orders=[WorkOrderListItem.model_validate(o) for o in recent],
    )

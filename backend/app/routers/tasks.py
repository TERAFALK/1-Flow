from datetime import datetime, date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, nulls_last
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import Task, WorkOrder, SalesLead, SalesLeadKind, User
from ..schemas import TaskCreate, TaskUpdate, TaskOut, TaskListItem

router = APIRouter(prefix="/api/work-orders", tags=["tasks"])


@router.get("/{order_id}/tasks", response_model=List[TaskOut])
def list_tasks(order_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    return (
        db.query(Task)
        .options(joinedload(Task.assigned_user))
        .filter(Task.work_order_id == order_id)
        .order_by(Task.id)
        .all()
    )


@router.post("/{order_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(
    order_id: int,
    body: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    task = Task(work_order_id=order_id, created_by=current_user.id, **body.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return db.query(Task).options(joinedload(Task.assigned_user)).get(task.id)


@router.put("/{order_id}/tasks/{task_id}", response_model=TaskOut)
def update_task(
    order_id: int,
    task_id: int,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.work_order_id == order_id).first()
    if not task:
        raise HTTPException(404, "Uppgift ej hittad")
    data = body.model_dump(exclude_unset=True)
    if "completed" in data:
        task.completed_at = datetime.utcnow() if data["completed"] else None
    for k, v in data.items():
        setattr(task, k, v)
    db.commit()
    db.refresh(task)
    return db.query(Task).options(joinedload(Task.assigned_user)).get(task.id)


@router.delete("/{order_id}/tasks/{task_id}", status_code=204)
def delete_task(
    order_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    task = db.query(Task).filter(Task.id == task_id, Task.work_order_id == order_id).first()
    if not task:
        raise HTTPException(404, "Uppgift ej hittad")
    db.delete(task)
    db.commit()


# ── Global uppgiftslista ──────────────────────────────────────────────────────
# Egen router eftersom filens prefix är /api/work-orders. Här samlas uppgifter
# från alla tre föräldrar så att man kan se vad som behöver göras utan att veta
# var uppgiften råkar ligga.

list_router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _parent_fields(task: Task) -> dict:
    """Var uppgiften hör hemma, med etikett och länk till detaljvyn."""
    if task.work_order_id and task.work_order:
        return dict(
            parent_type="arbetsorder",
            parent_label=task.work_order.order_number or f"#{task.work_order_id}",
            parent_link=f"#/work-orders/{task.work_order_id}",
            customer_name=task.work_order.customer.name if task.work_order.customer else None,
        )
    if task.lead_id and task.lead:
        lead = task.lead
        ffb = lead.kind == SalesLeadKind.feldbinder
        return dict(
            parent_type="offert",
            parent_label=lead.quote_number or lead.activity_number or f"#{lead.id}",
            parent_link=f"#{'/sales' if ffb else '/quotes'}/{lead.id}",
            customer_name=lead.customer.name if lead.customer else None,
        )
    if task.customer_id and task.customer:
        return dict(
            parent_type="kund",
            parent_label=task.customer.name,
            parent_link=f"#/customers/{task.customer_id}",
            customer_name=task.customer.name,
        )
    return dict(parent_type="", parent_label="", parent_link="", customer_name=None)


def _list_item(task: Task) -> TaskListItem:
    return TaskListItem(**TaskOut.model_validate(task).model_dump(), **_parent_fields(task))


@list_router.get("", response_model=List[TaskListItem])
def list_all_tasks(
    scope: str = Query("open", description="open | overdue | today | done | all"),
    assigned_to: Optional[int] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Uppgifter från arbetsordrar, offerter och kunder i en lista."""
    today_start = datetime.combine(date.today(), datetime.min.time())
    tomorrow = today_start + timedelta(days=1)

    query = db.query(Task).options(
        joinedload(Task.assigned_user),
        joinedload(Task.work_order).joinedload(WorkOrder.customer),
        joinedload(Task.lead).joinedload(SalesLead.customer),
        joinedload(Task.customer),
    )

    if scope == "done":
        query = query.filter(Task.completed.is_(True))
    elif scope == "overdue":
        query = query.filter(Task.completed.is_(False), Task.due_date < today_start)
    elif scope == "today":
        query = query.filter(
            Task.completed.is_(False),
            Task.due_date >= today_start, Task.due_date < tomorrow,
        )
    elif scope == "open":
        query = query.filter(Task.completed.is_(False))
    # scope == "all" filtrerar inte alls

    if assigned_to:
        query = query.filter(Task.assigned_to == assigned_to)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Task.title.ilike(like), Task.description.ilike(like)))

    # Närmast förfallodatum först, uppgifter utan datum sist
    tasks = query.order_by(nulls_last(Task.due_date.asc()), Task.id).all()
    return [_list_item(t) for t in tasks]


@list_router.put("/{task_id}", response_model=TaskListItem)
def update_any_task(
    task_id: int,
    body: TaskUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Uppdaterar oavsett förälder, så att listan kan bocka av utan att veta
    vilken av de tre parent-rutterna som gäller."""
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Uppgift ej hittad")
    fields = body.model_dump(exclude_unset=True)
    if "completed" in fields:
        task.completed_at = datetime.utcnow() if fields["completed"] else None
    for field, value in fields.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return _list_item(task)


@list_router.delete("/{task_id}", status_code=204)
def delete_any_task(task_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Uppgift ej hittad")
    db.delete(task)
    db.commit()

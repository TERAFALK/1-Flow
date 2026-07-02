from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import Task, WorkOrder, User
from ..schemas import TaskCreate, TaskUpdate, TaskOut

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

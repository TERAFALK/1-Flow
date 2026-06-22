from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import Activity, WorkOrder, User
from ..schemas import ActivityCreate, ActivityOut

router = APIRouter(prefix="/api/work-orders", tags=["activities"])


@router.get("/{order_id}/activities", response_model=List[ActivityOut])
def list_activities(order_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    return (
        db.query(Activity)
        .options(joinedload(Activity.creator))
        .filter(Activity.work_order_id == order_id)
        .order_by(Activity.created_at.desc())
        .all()
    )


@router.post("/{order_id}/activities", response_model=ActivityOut, status_code=201)
def create_activity(
    order_id: int,
    body: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    activity = Activity(work_order_id=order_id, created_by=current_user.id, **body.model_dump())
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return db.query(Activity).options(joinedload(Activity.creator)).get(activity.id)


@router.delete("/{order_id}/activities/{activity_id}", status_code=204)
def delete_activity(
    order_id: int,
    activity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    activity = db.query(Activity).filter(
        Activity.id == activity_id, Activity.work_order_id == order_id
    ).first()
    if not activity:
        raise HTTPException(404, "Aktivitet ej hittad")
    db.delete(activity)
    db.commit()

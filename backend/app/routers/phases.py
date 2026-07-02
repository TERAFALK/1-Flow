from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import WorkOrderPhase, WorkOrder, User
from ..schemas import WorkOrderPhaseCreate, WorkOrderPhaseUpdate, WorkOrderPhaseOut

router = APIRouter(prefix="/api/work-orders", tags=["phases"])


@router.get("/{order_id}/phases", response_model=List[WorkOrderPhaseOut])
def list_phases(order_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    return db.query(WorkOrderPhase).filter(WorkOrderPhase.work_order_id == order_id).order_by(WorkOrderPhase.sort_order).all()


@router.post("/{order_id}/phases", response_model=WorkOrderPhaseOut, status_code=201)
def create_phase(
    order_id: int,
    body: WorkOrderPhaseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    phase = WorkOrderPhase(work_order_id=order_id, **body.model_dump())
    db.add(phase)
    db.commit()
    db.refresh(phase)
    return phase


@router.put("/{order_id}/phases/{phase_id}", response_model=WorkOrderPhaseOut)
def update_phase(
    order_id: int,
    phase_id: int,
    body: WorkOrderPhaseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    phase = db.query(WorkOrderPhase).filter(
        WorkOrderPhase.id == phase_id, WorkOrderPhase.work_order_id == order_id
    ).first()
    if not phase:
        raise HTTPException(404, "Fas ej hittad")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(phase, k, v)
    db.commit()
    db.refresh(phase)
    return phase


@router.delete("/{order_id}/phases/{phase_id}", status_code=204)
def delete_phase(
    order_id: int,
    phase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    phase = db.query(WorkOrderPhase).filter(
        WorkOrderPhase.id == phase_id, WorkOrderPhase.work_order_id == order_id
    ).first()
    if not phase:
        raise HTTPException(404, "Fas ej hittad")
    db.delete(phase)
    db.commit()

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..deps import get_current_user
from ..schemas import TimeEntryCreate, TimeEntryStop, TimeEntryManual, TimeEntryOut
from ..models import TimeEntry, WorkOrder, User

router = APIRouter(prefix="/api/time-entries", tags=["time-entries"])


@router.get("", response_model=List[TimeEntryOut])
def list_time_entries(
    work_order_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(TimeEntry).options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order))
    if work_order_id:
        query = query.filter(TimeEntry.work_order_id == work_order_id)
    if user_id:
        query = query.filter(TimeEntry.user_id == user_id)
    return query.order_by(TimeEntry.start_time.desc()).limit(200).all()


@router.post("/start", response_model=TimeEntryOut, status_code=status.HTTP_201_CREATED)
def start_timer(
    body: TimeEntryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, body.work_order_id):
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")

    # Only one active timer per user allowed
    active = db.query(TimeEntry).filter(
        TimeEntry.user_id == current_user.id,
        TimeEntry.end_time.is_(None),
    ).first()
    if active:
        raise HTTPException(
            status_code=400,
            detail=f"Du har redan en aktiv tidmätning på AO {active.work_order_id}. Stoppa den först.",
        )

    entry = TimeEntry(
        work_order_id=body.work_order_id,
        user_id=current_user.id,
        start_time=datetime.utcnow(),
        description=body.description,
        entry_type=body.entry_type,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return db.query(TimeEntry).options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order)).get(entry.id)


@router.post("/manual", response_model=TimeEntryOut, status_code=status.HTTP_201_CREATED)
def create_manual_entry(
    body: TimeEntryManual,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, body.work_order_id):
        raise HTTPException(status_code=404, detail="Arbetsorder ej hittad")
    if body.end_time <= body.start_time:
        raise HTTPException(status_code=400, detail="Sluttid måste vara efter starttid")
    delta = body.end_time - body.start_time
    entry = TimeEntry(
        work_order_id=body.work_order_id,
        user_id=current_user.id,
        start_time=body.start_time,
        end_time=body.end_time,
        duration_minutes=int(delta.total_seconds() / 60),
        description=body.description,
        entry_type=body.entry_type,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return db.query(TimeEntry).options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order)).get(entry.id)


@router.post("/{entry_id}/stop", response_model=TimeEntryOut)
def stop_timer(
    entry_id: int,
    body: TimeEntryStop,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tidpost ej hittad")
    if entry.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Kan bara stoppa egna tidmätningar")
    if entry.end_time:
        raise HTTPException(status_code=400, detail="Tidmätningen är redan stoppad")

    entry.end_time = datetime.utcnow()
    delta = entry.end_time - entry.start_time
    entry.duration_minutes = int(delta.total_seconds() / 60)
    if body.description is not None:
        entry.description = body.description
    if body.entry_type is not None:
        entry.entry_type = body.entry_type
    db.commit()
    db.refresh(entry)
    return db.query(TimeEntry).options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order)).get(entry.id)


@router.get("/active", response_model=Optional[TimeEntryOut])
def get_active_timer(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.query(TimeEntry).options(joinedload(TimeEntry.user), joinedload(TimeEntry.work_order)).filter(
        TimeEntry.user_id == current_user.id,
        TimeEntry.end_time.is_(None),
    ).first()
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.get(TimeEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tidpost ej hittad")
    if entry.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Otillräckliga rättigheter")
    db.delete(entry)
    db.commit()

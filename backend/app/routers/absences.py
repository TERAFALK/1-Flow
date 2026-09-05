"""Frånvaro per person.

Finns för planeringsmötets skull: veckovyn visar vilka som är borta den veckan
så att det inte behöver hållas i huvudet. Registret föreslår en rad till
Noteringar, men skriver aldrig något automatiskt – i Word-dokumentet står
frånvaron både i veckoschemat och under Noteringar, och ett förslag som skriver
över det han själv skrivit vore värre än inget förslag.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import ABSENCE_KINDS, User, UserAbsence
from ..schemas import AbsenceCreate, AbsenceOut, AbsenceUpdate

router = APIRouter(prefix="/api/absences", tags=["absences"])


def _out(absence: UserAbsence) -> AbsenceOut:
    return AbsenceOut(
        id=absence.id,
        user_id=absence.user_id,
        user_name=absence.user.full_name if absence.user else "",
        start_date=absence.start_date,
        end_date=absence.end_date,
        kind=absence.kind,
        note=absence.note,
    )


def _validate(start: date, end: date, kind: Optional[str]):
    if end < start:
        raise HTTPException(status_code=400, detail="Slutdatum kan inte vara före startdatum")
    if kind and kind not in ABSENCE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Okänd frånvarotyp. Välj en av: {', '.join(ABSENCE_KINDS)}",
        )


@router.get("", response_model=List[AbsenceOut])
def list_absences(
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Frånvaro, valfritt begränsad till en period.

    Filtret är ett överlapp och inte "börjar inom perioden" – en semester som
    sträcker sig över tre veckor ska synas alla tre.
    """
    query = db.query(UserAbsence).options(joinedload(UserAbsence.user))
    if to_date:
        query = query.filter(UserAbsence.start_date <= to_date)
    if from_date:
        query = query.filter(UserAbsence.end_date >= from_date)
    rows = query.order_by(UserAbsence.start_date.desc(), UserAbsence.id.desc()).all()
    return [_out(a) for a in rows]


@router.post("", response_model=AbsenceOut, status_code=status.HTTP_201_CREATED)
def create_absence(
    body: AbsenceCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(User, body.user_id):
        raise HTTPException(status_code=404, detail="Användaren finns inte")
    _validate(body.start_date, body.end_date, body.kind)
    absence = UserAbsence(**body.model_dump())
    db.add(absence)
    db.commit()
    db.refresh(absence)
    return _out(absence)


@router.put("/{absence_id}", response_model=AbsenceOut)
def update_absence(
    absence_id: int,
    body: AbsenceUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    absence = db.get(UserAbsence, absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Frånvaron finns inte")
    data = body.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(absence, field, value)
    _validate(absence.start_date, absence.end_date, absence.kind)
    db.commit()
    db.refresh(absence)
    return _out(absence)


@router.delete("/{absence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_absence(
    absence_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    absence = db.get(UserAbsence, absence_id)
    if not absence:
        raise HTTPException(status_code=404, detail="Frånvaron finns inte")
    db.delete(absence)
    db.commit()

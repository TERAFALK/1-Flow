from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import SalesMilestoneDef, SalesOrderMilestone, User
from ..schemas import (
    SalesMilestoneDefCreate, SalesMilestoneDefUpdate, SalesMilestoneDefOut,
)

router = APIRouter(prefix="/api/sales/milestone-defs", tags=["sales-milestones"])


def _get(db: Session, def_id: int) -> SalesMilestoneDef:
    definition = db.get(SalesMilestoneDef, def_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Milstolpe ej hittad")
    return definition


@router.get("", response_model=List[SalesMilestoneDefOut])
def list_defs(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(SalesMilestoneDef)
    if not include_inactive:
        query = query.filter(SalesMilestoneDef.is_active.is_(True))
    return query.order_by(SalesMilestoneDef.sort_order, SalesMilestoneDef.id).all()


@router.post("", response_model=SalesMilestoneDefOut, status_code=status.HTTP_201_CREATED)
def create_def(
    body: SalesMilestoneDefCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if db.query(SalesMilestoneDef).filter(SalesMilestoneDef.key == body.key).first():
        raise HTTPException(status_code=400, detail="Nyckeln används redan")
    definition = SalesMilestoneDef(**body.model_dump())
    db.add(definition)
    db.commit()
    db.refresh(definition)
    return definition


@router.put("/{def_id}", response_model=SalesMilestoneDefOut)
def update_def(
    def_id: int,
    body: SalesMilestoneDefUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    definition = _get(db, def_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(definition, field, value)
    db.commit()
    db.refresh(definition)
    return definition


@router.delete("/{def_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_def(def_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Inaktiverar milstolpen i stället för att radera den. En hård radering skulle
    ta med sig ifyllda datum på gamla ordrar via cascaden."""
    definition = _get(db, def_id)
    used = db.query(SalesOrderMilestone.id).filter(SalesOrderMilestone.def_id == def_id).first()
    if used:
        definition.is_active = False
    else:
        db.delete(definition)
    db.commit()

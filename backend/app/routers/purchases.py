from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import Purchase, WorkOrder, Settings, User
from ..schemas import PurchaseCreate, PurchaseUpdate, PurchaseOut

router = APIRouter(prefix="/api/work-orders", tags=["purchases"])


def _next_purchase_number(db: Session) -> str:
    from datetime import datetime
    year = datetime.utcnow().year
    last = db.query(Purchase).filter(
        Purchase.purchase_number.like(f"INK-{year}-%")
    ).order_by(Purchase.purchase_number.desc()).first()
    n = 1
    if last and last.purchase_number:
        try:
            n = int(last.purchase_number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            pass
    return f"INK-{year}-{n:04d}"


@router.get("/{order_id}/purchases", response_model=List[PurchaseOut])
def list_purchases(order_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    return db.query(Purchase).filter(Purchase.work_order_id == order_id).order_by(Purchase.id).all()


@router.post("/{order_id}/purchases", response_model=PurchaseOut, status_code=201)
def create_purchase(
    order_id: int,
    body: PurchaseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")

    data = body.model_dump()
    if not data.get("purchase_number"):
        mode = db.get(Settings, "purchase_number_mode")
        if not mode or mode.value == "auto":
            data["purchase_number"] = _next_purchase_number(db)
        else:
            raise HTTPException(400, "Inköpsnummer krävs (manuellt läge)")

    purchase = Purchase(work_order_id=order_id, **data)
    db.add(purchase)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.put("/{order_id}/purchases/{purchase_id}", response_model=PurchaseOut)
def update_purchase(
    order_id: int,
    purchase_id: int,
    body: PurchaseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    purchase = db.query(Purchase).filter(
        Purchase.id == purchase_id, Purchase.work_order_id == order_id
    ).first()
    if not purchase:
        raise HTTPException(404, "Inköp ej hittat")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(purchase, k, v)
    db.commit()
    db.refresh(purchase)
    return purchase


@router.delete("/{order_id}/purchases/{purchase_id}", status_code=204)
def delete_purchase(
    order_id: int,
    purchase_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    purchase = db.query(Purchase).filter(
        Purchase.id == purchase_id, Purchase.work_order_id == order_id
    ).first()
    if not purchase:
        raise HTTPException(404, "Inköp ej hittat")
    db.delete(purchase)
    db.commit()

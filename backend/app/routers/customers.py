from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..schemas import (
    CustomerCreate, CustomerUpdate, CustomerOut,
    SalesLeadNoteCreate, SalesLeadNoteOut, SalesLeadFileOut, TaskCreate, TaskOut,
)
from .. import models

router = APIRouter(prefix="/api/customers", tags=["customers"])


@router.get("", response_model=List[CustomerOut])
def list_customers(
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    query = db.query(models.Customer)
    if q:
        query = query.filter(models.Customer.name.ilike(f"%{q}%"))
    return query.order_by(models.Customer.name).all()


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    body: CustomerCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    customer = models.Customer(**body.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    return customer


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    body: CustomerUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(customer, field, value)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_user),
):
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    # customer_id är NOT NULL på arbetsordrar och fordon – ge tydligt fel istället för 500
    if customer.work_orders:
        raise HTTPException(status_code=400, detail="Kunden har arbetsordrar – ta bort dem först")
    if customer.vehicles:
        raise HTTPException(status_code=400, detail="Kunden har fordon – ta bort dem först")
    if customer.sales_leads:
        raise HTTPException(status_code=400, detail="Kunden har offertförfrågningar – ta bort dem först")
    if customer.sales_orders:
        raise HTTPException(status_code=400, detail="Kunden har sålda ordrar – ta bort dem först")
    db.delete(customer)
    db.commit()


# ── CRM: aktiviteter och uppgifter på kunden ──────────────────────────────────
# En kundkontakt som varken är offert eller affär ska gå att logga ändå. Samma
# anteckningsmodell som säljuppföljningen använder, med kunden som förälder.

def _get_customer(db: Session, customer_id: int) -> models.Customer:
    customer = db.get(models.Customer, customer_id)
    if not customer:
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    return customer


def _note_out(note, source_label=None, source_link=None) -> SalesLeadNoteOut:
    return SalesLeadNoteOut(
        id=note.id,
        note_date=note.note_date,
        kind=note.kind,
        body=note.body,
        created_at=note.created_at,
        created_by_name=note.creator.full_name if note.creator else None,
        source_label=source_label,
        source_link=source_link,
        files=[SalesLeadFileOut.model_validate(f) for f in note.files],
    )


@router.get("/{customer_id}/notes", response_model=List[SalesLeadNoteOut])
def list_customer_notes(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    """Hela historiken för kunden: egna anteckningar plus uppföljningen från
    kundens förfrågningar och sålda ordrar, märkta med sin källa."""
    customer = _get_customer(db, customer_id)
    notes = [_note_out(n) for n in customer.crm_notes]

    for lead in customer.sales_leads:
        ffb = lead.kind == models.SalesLeadKind.feldbinder
        label = lead.quote_number or lead.activity_number or f"#{lead.id}"
        link = f"#{'/sales' if ffb else '/quotes'}/{lead.id}"
        notes += [
            _note_out(n, f"{'Förfrågan' if ffb else 'Offert'} {label}", link)
            for n in lead.lead_notes
        ]

    for order in customer.sales_orders:
        label = order.order_number or f"#{order.id}"
        notes += [
            _note_out(n, f"Order {label}", f"#/sales-orders/{order.id}")
            for n in order.order_notes
        ]

    notes.sort(key=lambda n: (n.note_date, n.id), reverse=True)
    return notes


@router.post("/{customer_id}/notes", response_model=SalesLeadNoteOut, status_code=201)
def create_customer_note(
    customer_id: int,
    body: SalesLeadNoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    _get_customer(db, customer_id)
    note = models.SalesLeadNote(
        customer_id=customer_id,
        note_date=body.note_date or date.today(),
        kind=body.kind,
        body=body.body,
        created_by=current_user.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_out(note)


@router.delete("/{customer_id}/notes/{note_id}", status_code=204)
def delete_customer_note(
    customer_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    # Bara kundens egna. En affärs anteckning tas bort där den hör hemma.
    note = db.query(models.SalesLeadNote).filter(
        models.SalesLeadNote.id == note_id,
        models.SalesLeadNote.customer_id == customer_id,
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Anteckning ej hittad")
    db.delete(note)
    db.commit()


@router.get("/{customer_id}/tasks", response_model=List[TaskOut])
def list_customer_tasks(
    customer_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_admin),
):
    _get_customer(db, customer_id)
    return (
        db.query(models.Task)
        .options(joinedload(models.Task.assigned_user))
        .filter(models.Task.customer_id == customer_id)
        .order_by(models.Task.id)
        .all()
    )


@router.post("/{customer_id}/tasks", response_model=TaskOut, status_code=201)
def create_customer_task(
    customer_id: int,
    body: TaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Uppdatering och radering går via /api/tasks/{id}, så vi slipper en tredje
    kopia av samma CRUD."""
    _get_customer(db, customer_id)
    task = models.Task(customer_id=customer_id, created_by=current_user.id, **body.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

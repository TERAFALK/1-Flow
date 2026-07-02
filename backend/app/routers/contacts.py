from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import ContactPerson, Customer, User
from ..schemas import ContactPersonCreate, ContactPersonUpdate, ContactPersonOut

router = APIRouter(prefix="/api/customers", tags=["contacts"])


@router.get("/{customer_id}/contacts", response_model=List[ContactPersonOut])
def list_contacts(
    customer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "Kund ej hittad")
    return db.query(ContactPerson).filter(ContactPerson.customer_id == customer_id).order_by(
        ContactPerson.is_primary.desc(), ContactPerson.name
    ).all()


@router.post("/{customer_id}/contacts", response_model=ContactPersonOut, status_code=201)
def create_contact(
    customer_id: int,
    body: ContactPersonCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "Kund ej hittad")
    contact = ContactPerson(customer_id=customer_id, **body.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact


@router.put("/{customer_id}/contacts/{contact_id}", response_model=ContactPersonOut)
def update_contact(
    customer_id: int,
    contact_id: int,
    body: ContactPersonUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    contact = db.query(ContactPerson).filter(
        ContactPerson.id == contact_id,
        ContactPerson.customer_id == customer_id,
    ).first()
    if not contact:
        raise HTTPException(404, "Kontaktperson ej hittad")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(contact, k, v)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{customer_id}/contacts/{contact_id}", status_code=204)
def delete_contact(
    customer_id: int,
    contact_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    contact = db.query(ContactPerson).filter(
        ContactPerson.id == contact_id,
        ContactPerson.customer_id == customer_id,
    ).first()
    if not contact:
        raise HTTPException(404, "Kontaktperson ej hittad")
    db.delete(contact)
    db.commit()

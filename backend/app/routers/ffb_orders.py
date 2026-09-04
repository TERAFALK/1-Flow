"""Beställningen till Feldbinder på en såld order.

Ersätter Word-mallen kunden fyllde i för hand: raden skapas förifylld ur ordern,
förfrågan och kunden första gången beställningen öppnas, redigeras i Flow och
laddas ner som PDF. Den senast sparade versionen läggs som bilaga på ordern så
att det går att se vad som skickades till FFB.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..ffb_order_pdf import build_ffb_order_pdf
from ..models import FfbOrder, SalesLead, SalesOrder, SalesOrderFile, User
from ..schemas import FfbOrderOut, FfbOrderUpdate
from ..uploads import remove_file, store_file

router = APIRouter(prefix="/api/sales/orders/{order_id}/ffb-order", tags=["ffb-orders"])

UPLOAD_ROOT = "/app/uploads/sales-orders"
FILE_GROUP = "FFB-beställning"

# Står förtryckta i mallen, men ska gå att ändra per beställning
DEFAULT_TERMS_PAYMENT = "10% Down payment, 90% on completion without deduction"
DEFAULT_TERMS_DELIVERY = "DAT Gothenburg"


def _get_order(db: Session, order_id: int) -> SalesOrder:
    order = (
        db.query(SalesOrder)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.lead).joinedload(SalesLead.contact_person),
        )
        .filter(SalesOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order ej hittad")
    return order


def _join(*parts) -> Optional[str]:
    """Slår ihop delar till en rad och hoppar över de tomma."""
    joined = " ".join(str(p).strip() for p in parts if p and str(p).strip())
    return joined or None


def _prefill(order: SalesOrder) -> FfbOrder:
    """Beställningen som den ser ut innan kunden justerat något.

    Allt vi redan vet fylls i; resten (chassi, ritningsnummer, transportmedium)
    finns inte i Flow och lämnas tomt åt kunden. Kontaktpersonens uppgifter går
    före kundens, precis som i ``sales_common.contact_fields``.
    """
    customer = order.customer
    lead = order.lead
    contact = lead.contact_person if lead else None

    return FfbOrder(
        order_id=order.id,
        doc_date=date.today(),
        vat_number=(customer.vat_number or customer.org_number) if customer else None,
        customer_number=customer.ffb_customer_number if customer else None,
        customer_name=customer.name if customer else None,
        address=customer.address if customer else None,
        postal_city=_join(customer.postal_code, customer.city) if customer else None,
        country=customer.country if customer else None,
        phone=(contact.phone if contact else None) or (customer.phone if customer else None),
        email=(contact.email if contact else None) or (customer.email if customer else None),
        contact_person=contact.name if contact else None,
        quantity=str(lead.quantity) if lead and lead.quantity else None,
        quotation_number=(lead.quote_number if lead else None) or order.order_number,
        # Veckan är det kunden själv skriver in i ordern, annars planerat datum
        delivery_time=order.delivery_week or (
            order.planned_delivery.isoformat() if order.planned_delivery else None
        ),
        product_type=order.product_type or (lead.product_type if lead else None),
        volume_approx=lead.size if lead else None,
        country_of_registration=customer.country if customer else None,
        special_feature=order.notes or (lead.description if lead else None),
        terms_payment=DEFAULT_TERMS_PAYMENT,
        terms_delivery=DEFAULT_TERMS_DELIVERY,
    )


def _get_or_create(db: Session, order: SalesOrder) -> FfbOrder:
    """Lazy skapande – även ordrar som såldes innan funktionen fanns får sin
    beställning förifylld första gången den öppnas."""
    ffb = db.query(FfbOrder).filter(FfbOrder.order_id == order.id).first()
    if ffb:
        return ffb
    ffb = _prefill(order)
    db.add(ffb)
    db.commit()
    db.refresh(ffb)
    return ffb


def _store_pdf(db: Session, order: SalesOrder, ffb: FfbOrder, user: User) -> None:
    """Sparar beställningen som bilaga på ordern och ersätter den förra.

    En fil per order, inte en hög versioner: bilagan ska visa vad beställningen
    innehåller nu, och den som vill se historiken har anteckningarna.
    """
    name = f"FFB-order-{order.order_number or order.id}.pdf"
    content = build_ffb_order_pdf(ffb).getvalue()

    previous = (
        db.query(SalesOrderFile)
        .filter(SalesOrderFile.order_id == order.id, SalesOrderFile.group_label == FILE_GROUP)
        .all()
    )
    for record in previous:
        remove_file(UPLOAD_ROOT, order.id, record.filename)
        db.delete(record)

    stored_name = store_file(UPLOAD_ROOT, order.id, name, content)
    db.add(SalesOrderFile(
        order_id=order.id,
        group_label=FILE_GROUP,
        filename=stored_name,
        original_name=name,
        mime_type="application/pdf",
        size_bytes=len(content),
        uploaded_by=user.id,
    ))
    db.commit()


@router.get("", response_model=FfbOrderOut)
def get_ffb_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get_order(db, order_id)
    return _get_or_create(db, order)


@router.put("", response_model=FfbOrderOut)
def update_ffb_order(
    order_id: int,
    body: FfbOrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    order = _get_order(db, order_id)
    ffb = _get_or_create(db, order)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ffb, field, value)
    ffb.updated_by = current_user.id
    db.commit()
    db.refresh(ffb)
    # Bilagan regenereras här så att den arkiverade filen alltid stämmer med
    # det som står i formuläret – nedladdningen blir då en ren GET.
    _store_pdf(db, order, ffb, current_user)
    db.refresh(ffb)
    return ffb


@router.get("/pdf")
def ffb_order_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get_order(db, order_id)
    ffb = _get_or_create(db, order)
    filename = f"FFB-order-{order.order_number or order.id}.pdf"
    return StreamingResponse(
        build_ffb_order_pdf(ffb),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

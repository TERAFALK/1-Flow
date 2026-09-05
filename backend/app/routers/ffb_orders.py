"""Beställningen till Feldbinder på en såld order.

Ersätter Word-mallen kunden fyllde i för hand: raden skapas förifylld ur ordern,
förfrågan och kunden första gången beställningen öppnas, redigeras i Flow och
laddas ner som PDF. Den senast sparade versionen läggs som bilaga på ordern så
att det går att se vad som skickades till FFB.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..ffb_pdf import build_ffb_order_pdf
from ..models import FfbOrder, SalesLead, SalesLeadFile, SalesOrder, SalesOrderFile, User
from ..schemas import FfbOrderOut, FfbOrderUpdate
from ..sales_common import ffb_customer_block
from ..uploads import copy_file, remove_file, safe_filename, store_file

router = APIRouter(prefix="/api/sales/orders/{order_id}/ffb-order", tags=["ffb-orders"])

UPLOAD_ROOT = "/app/uploads/sales-orders"
LEAD_UPLOAD_ROOT = "/app/uploads/sales-leads"
FILE_GROUP = "FFB-beställning"
# Samma etikett som på förfrågan, så att den kopierade filen känns igen
QUOTE_GROUP = "FFB-offertförfrågan"

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


def customer_block(order: SalesOrder) -> dict:
    """Kundblocket för den här ordern – kunden plus förfrågans kontaktperson."""
    return ffb_customer_block(order.customer, order.lead.contact_person if order.lead else None)


def pdf_name(order: SalesOrder) -> str:
    return safe_filename(f"FFB-order-{order.order_number or order.id}") + ".pdf"


def _out(order: SalesOrder, ffb: FfbOrder) -> FfbOrderOut:
    """Beställningens egna fält plus kundblocket som det ser ut just nu."""
    return FfbOrderOut.model_validate(ffb).model_copy(update=customer_block(order))


def _prefill(order: SalesOrder) -> FfbOrder:
    """Beställningen som den ser ut innan kunden justerat något.

    Allt vi redan vet fylls i; resten (chassi, ritningsnummer, transportmedium)
    finns inte i Flow och lämnas tomt åt kunden.
    """
    customer = order.customer
    lead = order.lead

    return FfbOrder(
        order_id=order.id,
        doc_date=date.today(),
        quantity=str(lead.quantity) if lead and lead.quantity else None,
        quotation_number=(lead.quote_number if lead else None) or order.order_number,
        # Veckan är det kunden själv skriver in i ordern, annars planerat datum
        delivery_time=order.delivery_week or (
            order.planned_delivery.isoformat() if order.planned_delivery else None
        ),
        product_type=order.product_type or (lead.product_type if lead else None),
        volume_approx=lead.size if lead else None,
        country_of_registration=customer.country if customer else None,
        # Förfrågans Beskrivning följer med flit inte med – den är en intern
        # sammanfattning av affären, inte en specifikation åt FFB
        special_feature=order.notes,
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


def _store_pdf(db: Session, order: SalesOrder, ffb: FfbOrder, user_id) -> None:
    """Sparar beställningen som bilaga på ordern och ersätter den förra.

    En fil per order, inte en hög versioner: bilagan ska visa vad beställningen
    innehåller nu, och den som vill se historiken har anteckningarna.
    """
    name = pdf_name(order)
    content = build_ffb_order_pdf(ffb, customer_block(order)).getvalue()

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
        uploaded_by=user_id,
    ))
    db.commit()


def _groups(db: Session, order_id: int) -> set:
    return {
        f.group_label
        for f in db.query(SalesOrderFile).filter(SalesOrderFile.order_id == order_id).all()
    }


def copy_quote_document(db: Session, order: SalesOrder, user_id) -> None:
    """Lägger offertförfrågan som gick till FFB på ordern som historik.

    Dokumentet skapas på förfrågan och kopieras hit när affären säljs, så att
    ordern bär hela kedjan på egen hand. Originalet ligger kvar på förfrågan.
    Har ingen begärt något pris via Flow finns det inget att kopiera.
    """
    if order.lead_id is None or QUOTE_GROUP in _groups(db, order.id):
        return

    source = (
        db.query(SalesLeadFile)
        .filter(
            SalesLeadFile.lead_id == order.lead_id,
            SalesLeadFile.group_label == QUOTE_GROUP,
        )
        .first()
    )
    if not source:
        return

    # Kopia och inte flytt: originalet ska ligga kvar på förfrågan
    stored_name = copy_file(LEAD_UPLOAD_ROOT, order.lead_id, UPLOAD_ROOT, order.id, source.filename)
    if not stored_name:
        return
    db.add(SalesOrderFile(
        order_id=order.id,
        group_label=QUOTE_GROUP,
        filename=stored_name,
        original_name=source.original_name,
        mime_type=source.mime_type,
        size_bytes=source.size_bytes,
        uploaded_by=user_id,
    ))
    db.commit()


def ensure_documents(db: Session, order: SalesOrder, user_id) -> None:
    """Båda FFB-dokumenten som bilagor på ordern. Anropas vid arkivering.

    Arkivet är historiken, så ordern ska bära dokumenten på egen hand: dels
    offertförfrågan från förfrågan, dels beställningen. Beställningen genereras
    om den saknas – en såld feldbinder-affär har alltid en, även om ingen hunnit
    öppna formuläret och spara.
    """
    copy_quote_document(db, order, user_id)
    if FILE_GROUP not in _groups(db, order.id):
        _store_pdf(db, order, _get_or_create(db, order), user_id)


@router.get("", response_model=FfbOrderOut)
def get_ffb_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get_order(db, order_id)
    return _out(order, _get_or_create(db, order))


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
    _store_pdf(db, order, ffb, current_user.id)
    db.refresh(ffb)
    return _out(order, ffb)


@router.get("/pdf")
def ffb_order_pdf(
    order_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get_order(db, order_id)
    ffb = _get_or_create(db, order)
    return StreamingResponse(
        build_ffb_order_pdf(ffb, customer_block(order)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_name(order)}"'},
    )

"""Offertförfrågan till Feldbinder på en förfrågan.

Ersätter Word-mallen "Quotation Request" som kunden fyllde i för hand för att be
FFB om ett pris. Samma upplägg som beställningen på ordersidan: raden skapas
förifylld första gången den öppnas, redigeras i Flow och laddas ner som PDF, och
den senast sparade versionen ligger som bilaga på förfrågan.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..ffb_pdf import build_ffb_quote_pdf
from ..models import FfbQuote, SalesLead, SalesLeadFile, SalesLeadKind, User
from ..sales_common import ffb_customer_block
from ..schemas import FfbQuoteOut, FfbQuoteUpdate
from ..uploads import remove_file, safe_filename, store_file

router = APIRouter(prefix="/api/sales/leads/{lead_id}/ffb-quote", tags=["ffb-quotes"])

UPLOAD_ROOT = "/app/uploads/sales-leads"
FILE_GROUP = "FFB-offertförfrågan"

# Står förtryckta i mallen, men ska gå att ändra per förfrågan
DEFAULT_TERMS_PAYMENT = "10% Down payment, 90% on completion without deduction"
DEFAULT_TERMS_DELIVERY = "DAT Gothenburg"


def _get_lead(db: Session, lead_id: int) -> SalesLead:
    lead = (
        db.query(SalesLead)
        .options(joinedload(SalesLead.customer), joinedload(SalesLead.contact_person))
        .filter(SalesLead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Förfrågan ej hittad")
    if lead.kind != SalesLeadKind.feldbinder:
        raise HTTPException(
            status_code=400,
            detail="Bara feldbinder-förfrågningar går via FFB",
        )
    return lead


def customer_block(lead: SalesLead) -> dict:
    return ffb_customer_block(lead.customer, lead.contact_person)


def _out(lead: SalesLead, quote: FfbQuote) -> FfbQuoteOut:
    """Förfrågans egna fält plus kundblocket som det ser ut just nu."""
    return FfbQuoteOut.model_validate(quote).model_copy(update=customer_block(lead))


def _prefill(lead: SalesLead) -> FfbQuote:
    """Det vi redan vet ur förfrågan. Chassi, ritningsnummer och transportmedium
    finns inte i Flow och lämnas tomma åt kunden."""
    return FfbQuote(
        lead_id=lead.id,
        doc_date=date.today(),
        product_type=lead.product_type,
        volume_approx=lead.size,
        country_of_registration=lead.customer.country if lead.customer else None,
        special_feature=lead.description,
        terms_payment=DEFAULT_TERMS_PAYMENT,
        terms_delivery=DEFAULT_TERMS_DELIVERY,
    )


def _get_or_create(db: Session, lead: SalesLead) -> FfbQuote:
    """Lazy skapande – även gamla förfrågningar får sin offertförfrågan
    förifylld första gången den öppnas."""
    quote = db.query(FfbQuote).filter(FfbQuote.lead_id == lead.id).first()
    if quote:
        return quote
    quote = _prefill(lead)
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote


def pdf_name(lead: SalesLead, prefix: str = "FFB-offertforfragan") -> str:
    return safe_filename(f"{prefix}-{lead.quote_number or lead.id}") + ".pdf"


def store_quote_pdf(db: Session, lead: SalesLead, quote: FfbQuote, user_id) -> SalesLeadFile:
    """Sparar offertförfrågan som bilaga på förfrågan och ersätter den förra.

    En fil per förfrågan, inte en hög versioner: bilagan ska visa vad som
    skickades till FFB senast.
    """
    name = pdf_name(lead)
    content = build_ffb_quote_pdf(quote, customer_block(lead)).getvalue()

    previous = (
        db.query(SalesLeadFile)
        .filter(SalesLeadFile.lead_id == lead.id, SalesLeadFile.group_label == FILE_GROUP)
        .all()
    )
    for record in previous:
        remove_file(UPLOAD_ROOT, lead.id, record.filename)
        db.delete(record)

    stored_name = store_file(UPLOAD_ROOT, lead.id, name, content)
    record = SalesLeadFile(
        lead_id=lead.id,
        group_label=FILE_GROUP,
        filename=stored_name,
        original_name=name,
        mime_type="application/pdf",
        size_bytes=len(content),
        uploaded_by=user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("", response_model=FfbQuoteOut)
def get_ffb_quote(
    lead_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    lead = _get_lead(db, lead_id)
    return _out(lead, _get_or_create(db, lead))


@router.put("", response_model=FfbQuoteOut)
def update_ffb_quote(
    lead_id: int,
    body: FfbQuoteUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    lead = _get_lead(db, lead_id)
    quote = _get_or_create(db, lead)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(quote, field, value)
    quote.updated_by = current_user.id
    db.commit()
    db.refresh(quote)
    # Bilagan regenereras här så att den arkiverade filen alltid stämmer med
    # det som står i formuläret – nedladdningen blir då en ren GET.
    store_quote_pdf(db, lead, quote, current_user.id)
    db.refresh(quote)
    return _out(lead, quote)


@router.get("/pdf")
def ffb_quote_pdf(
    lead_id: int,
    lang: str = Query("en", pattern="^(en|sv)$",
                      description="en = dokumentet till FFB, sv = underlag till slutkunden"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Offertförfrågan som PDF.

    Engelska är dokumentet som går till FFB. Svenska är samma uppgifter som
    underlag till slutkunden, med Flows sidhuvud i stället för FFB:s logotyp.
    Bara etiketterna byts – fritexten står kvar precis som den skrevs.
    """
    lead = _get_lead(db, lead_id)
    quote = _get_or_create(db, lead)
    name = pdf_name(lead) if lang == "en" else pdf_name(lead, prefix="Offertforfragan-sv")
    return StreamingResponse(
        build_ffb_quote_pdf(quote, customer_block(lead), lang=lang),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )

import os
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import (
    SalesLead, SalesLeadNote, SalesLeadFile, SalesLeadStatus,
    SalesOrder, SalesMilestoneDef, SalesOrderMilestone,
    Customer, ContactPerson, User,
)
from ..schemas import (
    SalesLeadCreate, SalesLeadUpdate, SalesLeadOut, SalesLeadListItem,
    SalesLeadNoteCreate, SalesLeadNoteOut, SalesLeadFileOut,
    SalesLeadConvert, SalesOrderOut, SalesPipelineStats,
)
from ..uploads import store_file, file_path, remove_file
from .sales_orders import order_out

router = APIRouter(prefix="/api/sales/leads", tags=["sales-leads"])

# Egen mapp under samma uploads-volym som arbetsordrarnas filer (se routers/files.py)
UPLOAD_ROOT = "/app/uploads/sales-leads"

# Statusar där affären fortfarande är i spel – används för nyckeltal och
# bevakningslistan så att avslutade och sålda inte ligger kvar och skräpar.
OPEN_STATUSES = (SalesLeadStatus.ny, SalesLeadStatus.skickad, SalesLeadStatus.jobbar)


def _get(db: Session, lead_id: int) -> SalesLead:
    lead = (
        db.query(SalesLead)
        .options(
            joinedload(SalesLead.customer),
            joinedload(SalesLead.contact_person),
            joinedload(SalesLead.assignee),
            joinedload(SalesLead.lead_notes).joinedload(SalesLeadNote.creator),
            joinedload(SalesLead.files),
        )
        .filter(SalesLead.id == lead_id)
        .first()
    )
    if not lead:
        raise HTTPException(status_code=404, detail="Förfrågan ej hittad")
    return lead


def _base_fields(lead: SalesLead) -> dict:
    """Fälten som listvyn och detaljvyn delar."""
    notes = sorted(lead.lead_notes, key=lambda n: (n.note_date, n.id), reverse=True)
    latest = notes[0] if notes else None
    # Kontaktpersonens e-post går före kundens – Excel hade e-posten per förfrågan
    email = (lead.contact_person.email if lead.contact_person else None) or (
        lead.customer.email if lead.customer else None
    )
    return dict(
        id=lead.id,
        activity_number=lead.activity_number,
        customer_id=lead.customer_id,
        customer_name=lead.customer.name if lead.customer else "",
        product_type=lead.product_type,
        size=lead.size,
        quantity=lead.quantity,
        status=lead.status,
        date_request=lead.date_request,
        date_sent_ffb=lead.date_sent_ffb,
        date_back_ffb=lead.date_back_ffb,
        date_sent_customer=lead.date_sent_customer,
        quote_number=lead.quote_number,
        estimated_value=lead.estimated_value,
        currency=lead.currency,
        next_followup_date=lead.next_followup_date,
        assignee_name=lead.assignee.full_name if lead.assignee else None,
        contact_email=email,
        last_note=latest.body if latest else None,
        last_note_date=latest.note_date if latest else None,
        note_count=len(lead.lead_notes),
        file_count=len(lead.files),
    )


def _note_out(note: SalesLeadNote) -> SalesLeadNoteOut:
    return SalesLeadNoteOut(
        id=note.id,
        note_date=note.note_date,
        kind=note.kind,
        body=note.body,
        created_at=note.created_at,
        created_by_name=note.creator.full_name if note.creator else None,
    )


def _out(db: Session, lead: SalesLead) -> SalesLeadOut:
    order = db.query(SalesOrder.id).filter(SalesOrder.lead_id == lead.id).first()
    notes = sorted(lead.lead_notes, key=lambda n: (n.note_date, n.id), reverse=True)
    return SalesLeadOut(
        **_base_fields(lead),
        contact_person_id=lead.contact_person_id,
        external_link=lead.external_link,
        lost_reason=lead.lost_reason,
        notes=lead.notes,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
        order_id=order[0] if order else None,
        lead_notes=[_note_out(n) for n in notes],
        files=[SalesLeadFileOut.model_validate(f) for f in lead.files],
    )


def _validate_refs(db: Session, customer_id: Optional[int], contact_person_id: Optional[int]):
    if customer_id is not None and not db.get(Customer, customer_id):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    if contact_person_id is not None:
        contact = db.get(ContactPerson, contact_person_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Kontaktperson ej hittad")
        if customer_id is not None and contact.customer_id != customer_id:
            raise HTTPException(status_code=400, detail="Kontaktpersonen tillhör en annan kund")


# ── Förfrågningar ─────────────────────────────────────────────────────────────

@router.get("", response_model=List[SalesLeadListItem])
def list_leads(
    q: Optional[str] = None,
    status_filter: Optional[SalesLeadStatus] = Query(None, alias="status"),
    customer_id: Optional[int] = None,
    followup: Optional[str] = Query(None, description="'overdue' = uppföljningsdatum har passerat"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = (
        db.query(SalesLead)
        .join(Customer, SalesLead.customer_id == Customer.id)
        .options(
            joinedload(SalesLead.customer),
            joinedload(SalesLead.contact_person),
            joinedload(SalesLead.assignee),
            joinedload(SalesLead.lead_notes),
            joinedload(SalesLead.files),
        )
    )
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Customer.name.ilike(like),
            SalesLead.activity_number.ilike(like),
            SalesLead.quote_number.ilike(like),
            SalesLead.product_type.ilike(like),
        ))
    if status_filter:
        query = query.filter(SalesLead.status == status_filter)
    if customer_id:
        query = query.filter(SalesLead.customer_id == customer_id)
    if followup == "overdue":
        query = query.filter(
            SalesLead.next_followup_date <= date.today(),
            SalesLead.status.in_(OPEN_STATUSES),
        )
    leads = query.order_by(SalesLead.date_request.desc().nullslast(), SalesLead.id.desc()).all()
    return [SalesLeadListItem(**_base_fields(l)) for l in leads]


@router.get("/stats", response_model=SalesPipelineStats)
def pipeline_stats(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    counts = dict(
        db.query(SalesLead.status, func.count(SalesLead.id)).group_by(SalesLead.status).all()
    )
    open_value = (
        db.query(func.coalesce(func.sum(SalesLead.estimated_value), 0))
        .filter(SalesLead.status.in_(OPEN_STATUSES))
        .scalar()
    )
    overdue = (
        db.query(func.count(SalesLead.id))
        .filter(
            SalesLead.next_followup_date <= date.today(),
            SalesLead.status.in_(OPEN_STATUSES),
        )
        .scalar()
    )
    return SalesPipelineStats(
        by_status={s.value: counts.get(s, 0) for s in SalesLeadStatus},
        open_leads=sum(counts.get(s, 0) for s in OPEN_STATUSES),
        overdue_followups=overdue or 0,
        open_value=open_value or 0,
    )


@router.post("", response_model=SalesLeadOut, status_code=status.HTTP_201_CREATED)
def create_lead(
    body: SalesLeadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _validate_refs(db, body.customer_id, body.contact_person_id)
    data = body.model_dump()
    # Förfrågningsdatumet är alltid ifyllt i Excel – sätt dagens om det utelämnas
    if not data.get("date_request"):
        data["date_request"] = date.today()
    lead = SalesLead(**data, created_by=current_user.id)
    db.add(lead)
    db.commit()
    return _out(db, _get(db, lead.id))


@router.get("/{lead_id}", response_model=SalesLeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _out(db, _get(db, lead_id))


@router.put("/{lead_id}", response_model=SalesLeadOut)
def update_lead(
    lead_id: int,
    body: SalesLeadUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    lead = _get(db, lead_id)
    fields = body.model_dump(exclude_unset=True)
    if "customer_id" in fields or "contact_person_id" in fields:
        # Kontaktpersonen kontrolleras mot den kund posten kommer att ha efteråt
        _validate_refs(
            db,
            fields.get("customer_id", lead.customer_id),
            fields.get("contact_person_id", lead.contact_person_id),
        )
    for field, value in fields.items():
        setattr(lead, field, value)
    db.commit()
    return _out(db, _get(db, lead_id))


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lead = _get(db, lead_id)
    if db.query(SalesOrder.id).filter(SalesOrder.lead_id == lead_id).first():
        raise HTTPException(status_code=400, detail="Förfrågan har en order och kan inte tas bort")
    # Filerna på disk följer inte med databasens cascade
    for f in lead.files:
        remove_file(UPLOAD_ROOT, lead_id, f.filename)
    db.delete(lead)
    db.commit()


# ── Uppföljningslogg ──────────────────────────────────────────────────────────

@router.post("/{lead_id}/notes", response_model=SalesLeadNoteOut, status_code=status.HTTP_201_CREATED)
def add_note(
    lead_id: int,
    body: SalesLeadNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, lead_id)
    note = SalesLeadNote(
        lead_id=lead_id,
        note_date=body.note_date or date.today(),
        kind=body.kind,
        body=body.body,
        created_by=current_user.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_out(note)


@router.delete("/{lead_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    lead_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    note = db.query(SalesLeadNote).filter(
        SalesLeadNote.id == note_id, SalesLeadNote.lead_id == lead_id
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Anteckning ej hittad")
    db.delete(note)
    db.commit()


# ── Filer (offert-PDF m.m.) ───────────────────────────────────────────────────

@router.get("/{lead_id}/files", response_model=List[SalesLeadFileOut])
def list_files(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    _get(db, lead_id)
    return (
        db.query(SalesLeadFile)
        .filter(SalesLeadFile.lead_id == lead_id)
        .order_by(SalesLeadFile.uploaded_at.desc())
        .all()
    )


@router.post("/{lead_id}/files", response_model=SalesLeadFileOut, status_code=status.HTTP_201_CREATED)
async def upload_lead_file(
    lead_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, lead_id)

    content = await file.read()
    stored_name = store_file(UPLOAD_ROOT, lead_id, file.filename or "", content)

    record = SalesLeadFile(
        lead_id=lead_id,
        filename=stored_name,
        original_name=file.filename or stored_name,
        mime_type=file.content_type,
        size_bytes=len(content),
        uploaded_by=current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{lead_id}/files/{file_id}/download")
def download_lead_file(
    lead_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = db.query(SalesLeadFile).filter(
        SalesLeadFile.id == file_id, SalesLeadFile.lead_id == lead_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fil ej hittad")
    path = file_path(UPLOAD_ROOT, lead_id, record.filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Fil saknas på disk")
    return FileResponse(
        path,
        filename=record.original_name,
        media_type=record.mime_type or "application/octet-stream",
    )


@router.delete("/{lead_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead_file(
    lead_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = db.query(SalesLeadFile).filter(
        SalesLeadFile.id == file_id, SalesLeadFile.lead_id == lead_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fil ej hittad")
    remove_file(UPLOAD_ROOT, lead_id, record.filename)
    db.delete(record)
    db.commit()


# ── Konvertering till order ───────────────────────────────────────────────────

@router.post("/{lead_id}/convert", response_model=SalesOrderOut, status_code=status.HTTP_201_CREATED)
def convert_to_order(
    lead_id: int,
    body: SalesLeadConvert = SalesLeadConvert(),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Markerar förfrågan som såld och skapar orderraden – motsvarar flytten från
    fliken "Offertförfrågan Lista" till årsfliken i kundens Excel."""
    lead = _get(db, lead_id)
    if db.query(SalesOrder.id).filter(SalesOrder.lead_id == lead_id).first():
        raise HTTPException(status_code=400, detail="Förfrågan är redan konverterad till order")

    order = SalesOrder(
        lead_id=lead.id,
        customer_id=lead.customer_id,
        order_number=body.order_number,
        # Excel skriver ihop objekt och storlek i typkolumnen: KIA + 28 = KIA28
        product_type=f"{lead.product_type or ''}{lead.size or ''}".strip() or None,
        price=body.price if body.price is not None else lead.estimated_value,
        currency=lead.currency or "EUR",
        commission=body.commission,
        sold_date=body.sold_date or date.today(),
    )
    db.add(order)
    db.flush()

    # Tomma milstolpsrader så att ordervyn kan renderas direkt
    for definition in db.query(SalesMilestoneDef).filter(SalesMilestoneDef.is_active.is_(True)).all():
        db.add(SalesOrderMilestone(order_id=order.id, def_id=definition.id))

    lead.status = SalesLeadStatus.sald
    lead.next_followup_date = None
    db.commit()
    return order_out(db, order.id)

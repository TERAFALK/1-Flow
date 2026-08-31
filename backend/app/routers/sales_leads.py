import os
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_, func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import (
    SalesLead, SalesLeadNote, SalesLeadFile, SalesLeadStatus, SalesLeadKind,
    SalesActivity, SalesOrder, SalesOrderFile, SalesMilestoneDef, SalesOrderMilestone,
    Customer, ContactPerson, WorkOrder, WorkOrderStatus, Settings, User,
)
from ..schemas import (
    SalesLeadCreate, SalesLeadUpdate, SalesLeadOut, SalesLeadListItem,
    SalesLeadNoteCreate, SalesLeadNoteOut, SalesLeadFileOut,
    SalesLeadConvert, SalesLeadToWorkOrder, SalesOrderOut, SalesPipelineStats,
    SalesActivityCreate, SalesActivityUpdate, SalesActivityOut, SalesScheduleItem,
)
from ..sales_common import contact_fields, activity_out, lead_schedule, next_activity_sort
from ..sales_pdf import build_lead_pdf
from ..uploads import store_file, file_path, remove_file
from .sales_orders import order_out, UPLOAD_ROOT as ORDER_UPLOAD_ROOT
from .work_orders import _next_order_number

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
            joinedload(SalesLead.activities),
            joinedload(SalesLead.work_order),
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
    return dict(
        id=lead.id,
        kind=lead.kind,
        description=lead.description,
        activity_number=lead.activity_number,
        customer_id=lead.customer_id,
        # Kunduppgifterna visas likadant på förfrågan och på order
        **contact_fields(lead.customer, lead.contact_person),
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
    order = (
        db.query(SalesOrder.id, SalesOrder.order_number)
        .filter(SalesOrder.lead_id == lead.id)
        .first()
    )
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
        order_number=order[1] if order else None,
        work_order_id=lead.work_order_id,
        work_order_number=lead.work_order.order_number if lead.work_order else None,
        archived_at=lead.archived_at,
        lead_notes=[_note_out(n) for n in notes],
        files=[SalesLeadFileOut.model_validate(f) for f in lead.files],
        activities=[activity_out(a) for a in lead.activities],
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
    kind: Optional[SalesLeadKind] = None,
    customer_id: Optional[int] = None,
    archived: bool = False,
    followup: Optional[str] = Query(None, description="'overdue' = uppföljningsdatum har passerat"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Utan ?kind= kommer båda sorterna med. Arkiverade göms som standard."""
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
        .filter(SalesLead.archived_at.isnot(None) if archived else SalesLead.archived_at.is_(None))
    )
    if kind:
        query = query.filter(SalesLead.kind == kind)
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
def pipeline_stats(
    kind: Optional[SalesLeadKind] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    def scoped(query):
        query = query.filter(SalesLead.archived_at.is_(None))
        return query.filter(SalesLead.kind == kind) if kind else query

    counts = dict(
        scoped(db.query(SalesLead.status, func.count(SalesLead.id)))
        .group_by(SalesLead.status).all()
    )
    open_value = scoped(
        db.query(func.coalesce(func.sum(SalesLead.estimated_value), 0))
        .filter(SalesLead.status.in_(OPEN_STATUSES))
    ).scalar()
    overdue = scoped(
        db.query(func.count(SalesLead.id)).filter(
            SalesLead.next_followup_date <= date.today(),
            SalesLead.status.in_(OPEN_STATUSES),
        )
    ).scalar()
    return SalesPipelineStats(
        by_status={s.value: counts.get(s, 0) for s in SalesLeadStatus},
        open_leads=sum(counts.get(s, 0) for s in OPEN_STATUSES),
        overdue_followups=overdue or 0,
        open_value=open_value or 0,
        currency="SEK" if kind == SalesLeadKind.verkstad else "EUR",
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
    # Verkstadsjobb offereras i kronor, Feldbinder-affärer i euro
    if data.get("kind") == SalesLeadKind.verkstad and not body.model_fields_set & {"currency"}:
        data["currency"] = "SEK"
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
    """Tar bort förfrågan helt, inklusive en eventuell order som skapats ur den.
    Gränssnittet namnger ordern i bekräftelsedialogen innan det anropar hit."""
    lead = _get(db, lead_id)

    # Filerna på disk följer inte med databasens cascade
    for f in lead.files:
        remove_file(UPLOAD_ROOT, lead_id, f.filename)

    orders = db.query(SalesOrder).filter(SalesOrder.lead_id == lead_id).all()
    for order in orders:
        for f in db.query(SalesOrderFile).filter(SalesOrderFile.order_id == order.id).all():
            remove_file(ORDER_UPLOAD_ROOT, order.id, f.filename)
        db.delete(order)

    db.delete(lead)
    db.commit()


# ── Schema och egna aktiviteter ───────────────────────────────────────────────

@router.get("/{lead_id}/schedule", response_model=List[SalesScheduleItem])
def get_schedule(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Gantt-underlaget: datumfälten som automatiska poster plus egna aktiviteter."""
    return lead_schedule(_get(db, lead_id))


@router.get("/{lead_id}/activities", response_model=List[SalesActivityOut])
def list_activities(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [activity_out(a) for a in _get(db, lead_id).activities]


@router.post("/{lead_id}/activities", response_model=SalesActivityOut, status_code=status.HTTP_201_CREATED)
def create_activity(
    lead_id: int,
    body: SalesActivityCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    lead = _get(db, lead_id)
    data = body.model_dump()
    if data.get("sort_order") is None:
        data["sort_order"] = next_activity_sort(lead.activities)
    activity = SalesActivity(lead_id=lead_id, **data)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity_out(activity)


@router.put("/{lead_id}/activities/{activity_id}", response_model=SalesActivityOut)
def update_activity(
    lead_id: int,
    activity_id: int,
    body: SalesActivityUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    activity = db.query(SalesActivity).filter(
        SalesActivity.id == activity_id, SalesActivity.lead_id == lead_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Aktivitet ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity_out(activity)


@router.delete("/{lead_id}/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(
    lead_id: int,
    activity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    activity = db.query(SalesActivity).filter(
        SalesActivity.id == activity_id, SalesActivity.lead_id == lead_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Aktivitet ej hittad")
    db.delete(activity)
    db.commit()


@router.get("/{lead_id}/pdf")
def lead_pdf(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lead = _get(db, lead_id)
    return StreamingResponse(
        build_lead_pdf(lead),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="forfragan-{lead_id}.pdf"'},
    )


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
    if lead.kind != SalesLeadKind.feldbinder:
        raise HTTPException(
            status_code=400,
            detail="Verkstadsofferter blir en arbetsorder – använd convert-to-work-order",
        )
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


# ── Arkivering ────────────────────────────────────────────────────────────────

@router.post("/{lead_id}/archive", response_model=SalesLeadOut)
def archive_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Lägger undan förfrågan utan att radera den. Används av Offerter-arkivet."""
    lead = _get(db, lead_id)
    if lead.archived_at is None:
        lead.archived_at = datetime.utcnow()
        db.commit()
    return _out(db, _get(db, lead_id))


@router.post("/{lead_id}/unarchive", response_model=SalesLeadOut)
def unarchive_lead(lead_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    lead = _get(db, lead_id)
    lead.archived_at = None
    db.commit()
    return _out(db, _get(db, lead_id))


# ── Verkstadsoffert blir arbetsorder ──────────────────────────────────────────

@router.post("/{lead_id}/convert-to-work-order", status_code=status.HTTP_201_CREATED)
def convert_to_work_order(
    lead_id: int,
    body: SalesLeadToWorkOrder = SalesLeadToWorkOrder(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """En såld verkstadsoffert blir en arbetsorder istället för en FFB-order.
    Returnerar den skapade arbetsordern så att gränssnittet kan hoppa dit."""
    lead = _get(db, lead_id)
    if lead.kind != SalesLeadKind.verkstad:
        raise HTTPException(
            status_code=400,
            detail="Bara verkstadsofferter blir arbetsorder – Feldbinder-affärer blir en såld order",
        )
    if lead.work_order_id:
        raise HTTPException(status_code=400, detail="Offerten har redan en arbetsorder")

    description = body.description or lead.description or lead.notes
    if not description:
        raise HTTPException(
            status_code=400,
            detail="Arbetsordern behöver en beskrivning – fyll i beskrivningen på offerten först",
        )

    # Samma numrering som när en arbetsorder skapas manuellt: automatiskt om inte
    # inställningen står på manuell numrering.
    mode = db.get(Settings, "order_number_mode")
    order_number = body.order_number
    if not order_number:
        if mode and mode.value == "manual":
            raise HTTPException(status_code=400, detail="Ange ordernummer – manuell numrering är vald")
        order_number = _next_order_number(db)
    if db.query(WorkOrder).filter(WorkOrder.order_number == order_number).first():
        raise HTTPException(status_code=400, detail=f"Ordernummer {order_number} används redan")

    wo = WorkOrder(
        order_number=order_number,
        customer_id=lead.customer_id,
        contact_person_id=lead.contact_person_id,
        vehicle_id=body.vehicle_id,
        description=description,
        status=WorkOrderStatus.ny,
        assigned_to=body.assigned_to,
        scheduled_date=body.scheduled_date,
        created_by=current_user.id,
    )
    db.add(wo)
    db.flush()

    lead.work_order_id = wo.id
    lead.status = SalesLeadStatus.sald
    lead.next_followup_date = None
    db.commit()
    db.refresh(wo)
    return {"id": wo.id, "order_number": wo.order_number}

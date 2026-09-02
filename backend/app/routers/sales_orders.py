import os
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import or_, extract, func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import (
    SalesOrder, SalesOrderMilestone, SalesMilestoneDef, SalesLead,
    SalesOrderAoc, SalesOrderFile, SalesActivity, SalesLeadNote, Customer, User,
)
from ..schemas import (
    SalesOrderCreate, SalesOrderUpdate, SalesOrderOut, SalesOrderListItem,
    SalesOrderMilestoneOut, SalesOrderMilestoneUpdate,
    SalesOrderAocCreate, SalesOrderAocUpdate, SalesOrderAocOut, SalesOrderFileOut,
    SalesCommissionRow, SalesCommissionSummary,
    SalesLeadNoteCreate, SalesLeadNoteOut, SalesLeadFileOut,
    SalesActivityCreate, SalesActivityUpdate, SalesActivityOut, SalesScheduleItem,
)
from ..sales_common import contact_fields, activity_out, order_schedule, next_activity_sort
from ..sales_pdf import build_order_pdf
from ..uploads import store_file, file_path, remove_file

router = APIRouter(prefix="/api/sales/orders", tags=["sales-orders"])

UPLOAD_ROOT = "/app/uploads/sales-orders"


def _get(db: Session, order_id: int) -> SalesOrder:
    order = (
        db.query(SalesOrder)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.milestones).joinedload(SalesOrderMilestone.definition),
            joinedload(SalesOrder.aocs).joinedload(SalesOrderAoc.files),
            joinedload(SalesOrder.files),
            joinedload(SalesOrder.activities),
            joinedload(SalesOrder.order_notes).joinedload(SalesLeadNote.creator),
            joinedload(SalesOrder.lead).joinedload(SalesLead.contact_person),
            joinedload(SalesOrder.lead).joinedload(SalesLead.lead_notes).joinedload(SalesLeadNote.creator),
        )
        .filter(SalesOrder.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order ej hittad")
    return order


def _is_done(m: SalesOrderMilestone) -> bool:
    """En milstolpe räknas som klar när den fått ett värde – oavsett om det är ett
    datum, en fritext eller en ikryssad ruta. Speglar hur cellerna används i Excel."""
    return bool(m.completed or m.value_date or (m.value_text or "").strip())


def _list_fields(order: SalesOrder) -> dict:
    active = [m for m in order.milestones if m.definition and m.definition.is_active]
    return dict(
        id=order.id,
        lead_id=order.lead_id,
        customer_id=order.customer_id,
        # Kontaktpersonen sitter på förfrågan som ordern kom ur
        **contact_fields(order.customer, order.lead.contact_person if order.lead else None),
        order_number=order.order_number,
        serial_number=order.serial_number,
        product_type=order.product_type,
        price=order.price,
        currency=order.currency,
        commission=order.commission,
        commission_paid_date=order.commission_paid_date,
        sold_date=order.sold_date,
        delivery_date=order.delivery_date,
        planned_delivery=order.planned_delivery,
        delivery_week=order.delivery_week,
        registration_number=order.registration_number,
        weight_kg=order.weight_kg,
        visit_ffb=order.visit_ffb,
        sort_index=order.sort_index,
        archived_at=order.archived_at,
        milestones_done=sum(1 for m in active if _is_done(m)),
        milestones_total=len(active),
    )


def _milestone_out(m: SalesOrderMilestone) -> SalesOrderMilestoneOut:
    d = m.definition
    return SalesOrderMilestoneOut(
        def_id=d.id,
        key=d.key,
        group_label=d.group_label,
        label=d.label,
        value_type=d.value_type,
        sort_order=d.sort_order,
        value_date=m.value_date,
        value_text=m.value_text,
        completed=_is_done(m),
        updated_at=m.updated_at,
    )


def order_out(db: Session, order_id: int) -> SalesOrderOut:
    """Delad av den här modulen och av lead-konverteringen i sales_leads.py."""
    order = _get(db, order_id)
    _ensure_milestones(db, order)
    milestones = [m for m in order.milestones if m.definition and m.definition.is_active]
    milestones.sort(key=lambda m: (m.definition.sort_order, m.definition.id))
    aocs = sorted(order.aocs, key=lambda a: (a.sort_order or 0, a.id))
    return SalesOrderOut(
        **_list_fields(order),
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
        milestones=[_milestone_out(m) for m in milestones],
        aocs=[_aoc_out(a) for a in aocs],
        activities=[activity_out(a) for a in order.activities],
        order_notes=_notes_for(order),
        # Bara avsnittsbilagorna här – AOC-filerna följer med sitt AOC ovan
        files=[
            SalesOrderFileOut.model_validate(f)
            for f in sorted(order.files, key=lambda f: f.id)
            if f.aoc_id is None
        ],
    )


def _note_out(note: SalesLeadNote, from_lead: bool = False) -> SalesLeadNoteOut:
    return SalesLeadNoteOut(
        id=note.id,
        note_date=note.note_date,
        kind=note.kind,
        body=note.body,
        created_at=note.created_at,
        created_by_name=note.creator.full_name if note.creator else None,
        from_lead=from_lead,
        files=[SalesLeadFileOut.model_validate(f) for f in note.files],
    )


def _notes_for(order: SalesOrder) -> List[SalesLeadNoteOut]:
    """Orderns egen uppföljning plus förfrågans logg. Den senare markeras som
    historik så att gränssnittet kan visa den utan redigeringsmöjlighet."""
    notes = [_note_out(n) for n in order.order_notes]
    if order.lead:
        notes += [_note_out(n, from_lead=True) for n in order.lead.lead_notes]
    notes.sort(key=lambda n: (n.note_date, n.id), reverse=True)
    return notes


def _aoc_out(aoc: SalesOrderAoc) -> SalesOrderAocOut:
    return SalesOrderAocOut(
        id=aoc.id,
        aoc_number=aoc.aoc_number,
        sent_customer=aoc.sent_customer,
        mailed_ffb=aoc.mailed_ffb,
        cost_eur=aoc.cost_eur,
        notes=aoc.notes,
        sort_order=aoc.sort_order,
        files=[SalesOrderFileOut.model_validate(f) for f in sorted(aoc.files, key=lambda f: f.id)],
    )


def _ensure_milestones(db: Session, order: SalesOrder) -> None:
    """Skapar rader för milstolpar som lagts till efter att ordern skapades, så att
    en ny milstolpe i mallen dyker upp på alla befintliga ordrar."""
    have = {m.def_id for m in order.milestones}
    missing = (
        db.query(SalesMilestoneDef)
        .filter(SalesMilestoneDef.is_active.is_(True), ~SalesMilestoneDef.id.in_(have or [0]))
        .all()
    )
    if not missing:
        return
    for definition in missing:
        db.add(SalesOrderMilestone(order_id=order.id, def_id=definition.id))
    db.commit()
    db.refresh(order)


# ── Ordrar ────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[SalesOrderListItem])
def list_orders(
    year: Optional[int] = None,
    q: Optional[str] = None,
    customer_id: Optional[int] = None,
    archived: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Arkiverade ordrar göms som standard – de hämtas med ?archived=true av
    Arkiv-fliken. Provisionen räknar däremot alltid med dem."""
    query = (
        db.query(SalesOrder)
        .join(Customer, SalesOrder.customer_id == Customer.id)
        .options(
            joinedload(SalesOrder.customer),
            joinedload(SalesOrder.milestones).joinedload(SalesOrderMilestone.definition),
            joinedload(SalesOrder.lead).joinedload(SalesLead.contact_person),
        )
        .filter(SalesOrder.archived_at.isnot(None) if archived else SalesOrder.archived_at.is_(None))
    )
    if year:
        query = query.filter(extract("year", SalesOrder.sold_date) == year)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Customer.name.ilike(like),
            SalesOrder.order_number.ilike(like),
            SalesOrder.serial_number.ilike(like),
            SalesOrder.product_type.ilike(like),
            SalesOrder.registration_number.ilike(like),
        ))
    if customer_id:
        query = query.filter(SalesOrder.customer_id == customer_id)
    orders = query.order_by(
        SalesOrder.sold_date.desc().nullslast(), SalesOrder.id.desc()
    ).all()
    return [SalesOrderListItem(**_list_fields(o)) for o in orders]


@router.get("/years", response_model=List[int])
def list_years(
    archived: Optional[bool] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    query = db.query(extract("year", SalesOrder.sold_date)).filter(SalesOrder.sold_date.isnot(None))
    if archived is True:
        query = query.filter(SalesOrder.archived_at.isnot(None))
    elif archived is False:
        query = query.filter(SalesOrder.archived_at.is_(None))
    rows = query.distinct().all()
    return sorted({int(r[0]) for r in rows}, reverse=True)


@router.get("/commission", response_model=SalesCommissionSummary)
def commission_summary(
    year: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Ersätter fliken 'Kommission' – provision per order plus årssumma."""
    query = db.query(SalesOrder).options(joinedload(SalesOrder.customer))
    if year:
        query = query.filter(extract("year", SalesOrder.sold_date) == year)
    orders = query.order_by(SalesOrder.sold_date.asc().nullslast(), SalesOrder.id.asc()).all()

    rows = [
        SalesCommissionRow(
            order_id=o.id,
            order_number=o.order_number,
            customer_name=o.customer.name if o.customer else "",
            product_type=o.product_type,
            sold_date=o.sold_date,
            price=o.price,
            commission=o.commission,
            commission_paid_date=o.commission_paid_date,
        )
        for o in orders
    ]
    zero = Decimal("0")
    return SalesCommissionSummary(
        year=year,
        rows=rows,
        total_price=sum((o.price or zero for o in orders), zero),
        total_commission=sum((o.commission or zero for o in orders), zero),
        paid_commission=sum((o.commission or zero for o in orders if o.commission_paid_date), zero),
        unpaid_commission=sum((o.commission or zero for o in orders if not o.commission_paid_date), zero),
    )


@router.post("", response_model=SalesOrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    body: SalesOrderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(Customer, body.customer_id):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    if body.lead_id is not None:
        if not db.get(SalesLead, body.lead_id):
            raise HTTPException(status_code=404, detail="Förfrågan ej hittad")
        if db.query(SalesOrder.id).filter(SalesOrder.lead_id == body.lead_id).first():
            raise HTTPException(status_code=400, detail="Förfrågan har redan en order")
    order = SalesOrder(**body.model_dump())
    db.add(order)
    db.commit()
    return order_out(db, order.id)


@router.get("/{order_id}", response_model=SalesOrderOut)
def get_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return order_out(db, order_id)


@router.put("/{order_id}", response_model=SalesOrderOut)
def update_order(
    order_id: int,
    body: SalesOrderUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get(db, order_id)
    fields = body.model_dump(exclude_unset=True)
    if fields.get("customer_id") and not db.get(Customer, fields["customer_id"]):
        raise HTTPException(status_code=404, detail="Kund ej hittad")
    for field, value in fields.items():
        setattr(order, field, value)
    db.commit()
    return order_out(db, order_id)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    order = _get(db, order_id)
    # Databasens cascade tar filraderna, men inte bytena på uploads-volymen
    for f in db.query(SalesOrderFile).filter(SalesOrderFile.order_id == order_id).all():
        remove_file(UPLOAD_ROOT, order_id, f.filename)
    db.delete(order)
    db.commit()


# ── Milstolpar ────────────────────────────────────────────────────────────────

@router.get("/{order_id}/milestones", response_model=List[SalesOrderMilestoneOut])
def list_milestones(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return order_out(db, order_id).milestones


@router.put("/{order_id}/milestones/{def_id}", response_model=SalesOrderMilestoneOut)
def set_milestone(
    order_id: int,
    def_id: int,
    body: SalesOrderMilestoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, order_id)
    if not db.get(SalesMilestoneDef, def_id):
        raise HTTPException(status_code=404, detail="Milstolpe ej hittad")

    milestone = db.query(SalesOrderMilestone).filter(
        SalesOrderMilestone.order_id == order_id,
        SalesOrderMilestone.def_id == def_id,
    ).first()
    if not milestone:
        milestone = SalesOrderMilestone(order_id=order_id, def_id=def_id)
        db.add(milestone)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(milestone, field, value)
    milestone.updated_by = current_user.id
    db.commit()
    db.refresh(milestone)
    return _milestone_out(milestone)


# ── AOC-intyg ─────────────────────────────────────────────────────────────────

def _get_aoc(db: Session, order_id: int, aoc_id: int) -> SalesOrderAoc:
    aoc = db.query(SalesOrderAoc).filter(
        SalesOrderAoc.id == aoc_id, SalesOrderAoc.order_id == order_id
    ).first()
    if not aoc:
        raise HTTPException(status_code=404, detail="AOC ej hittat")
    return aoc


@router.get("/{order_id}/aocs", response_model=List[SalesOrderAocOut])
def list_aocs(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    order = _get(db, order_id)
    return [_aoc_out(a) for a in sorted(order.aocs, key=lambda a: (a.sort_order or 0, a.id))]


@router.post("/{order_id}/aocs", response_model=SalesOrderAocOut, status_code=status.HTTP_201_CREATED)
def create_aoc(
    order_id: int,
    body: SalesOrderAocCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get(db, order_id)
    data = body.model_dump()
    if data.get("sort_order") is None:
        # Nya intyg hamnar sist – NB001, NB002, NB003 i den ordning de utfärdas
        data["sort_order"] = max((a.sort_order or 0 for a in order.aocs), default=-10) + 10
    aoc = SalesOrderAoc(order_id=order_id, **data)
    db.add(aoc)
    db.commit()
    db.refresh(aoc)
    return _aoc_out(aoc)


@router.put("/{order_id}/aocs/{aoc_id}", response_model=SalesOrderAocOut)
def update_aoc(
    order_id: int,
    aoc_id: int,
    body: SalesOrderAocUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    aoc = _get_aoc(db, order_id, aoc_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(aoc, field, value)
    db.commit()
    db.refresh(aoc)
    return _aoc_out(aoc)


@router.delete("/{order_id}/aocs/{aoc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_aoc(
    order_id: int,
    aoc_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    aoc = _get_aoc(db, order_id, aoc_id)
    # Databasens cascade tar filraderna, men inte bytena på disken
    for f in aoc.files:
        remove_file(UPLOAD_ROOT, order_id, f.filename)
    db.delete(aoc)
    db.commit()


# ── Bilagor per avsnitt eller AOC ─────────────────────────────────────────────

@router.get("/{order_id}/files", response_model=List[SalesOrderFileOut])
def list_order_files(
    order_id: int,
    group: Optional[str] = None,
    aoc_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    _get(db, order_id)
    query = db.query(SalesOrderFile).filter(SalesOrderFile.order_id == order_id)
    if group is not None:
        query = query.filter(SalesOrderFile.group_label == group)
    if aoc_id is not None:
        query = query.filter(SalesOrderFile.aoc_id == aoc_id)
    return query.order_by(SalesOrderFile.uploaded_at.desc()).all()


@router.post("/{order_id}/files", response_model=SalesOrderFileOut, status_code=status.HTTP_201_CREATED)
async def upload_order_file(
    order_id: int,
    group: Optional[str] = Query(None, description="Avsnittets rubrik, t.ex. Lackering"),
    aoc_id: Optional[int] = Query(None, description="Bilaga till ett enskilt AOC-intyg"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, order_id)
    if aoc_id is not None:
        # Kontrollera att intyget hör till ordern innan filen skrivs
        _get_aoc(db, order_id, aoc_id)
        group = None  # AOC-bilagor tillhör intyget, inte ett avsnitt

    content = await file.read()
    stored_name = store_file(UPLOAD_ROOT, order_id, file.filename or "", content)

    record = SalesOrderFile(
        order_id=order_id,
        group_label=group,
        aoc_id=aoc_id,
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


@router.get("/{order_id}/files/{file_id}/download")
def download_order_file(
    order_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = db.query(SalesOrderFile).filter(
        SalesOrderFile.id == file_id, SalesOrderFile.order_id == order_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fil ej hittad")
    path = file_path(UPLOAD_ROOT, order_id, record.filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Fil saknas på disk")
    return FileResponse(
        path,
        filename=record.original_name,
        media_type=record.mime_type or "application/octet-stream",
    )


@router.delete("/{order_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_file(
    order_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = db.query(SalesOrderFile).filter(
        SalesOrderFile.id == file_id, SalesOrderFile.order_id == order_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fil ej hittad")
    remove_file(UPLOAD_ROOT, order_id, record.filename)
    db.delete(record)
    db.commit()


# ── Arkivering ────────────────────────────────────────────────────────────────

@router.post("/{order_id}/archive", response_model=SalesOrderOut)
def archive_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Avslutar ordern. Den försvinner ur Sålda ordrar och hamnar under Arkiv,
    men räknas fortfarande med i provisionen."""
    order = _get(db, order_id)
    if order.archived_at is None:
        order.archived_at = datetime.utcnow()
        db.commit()
    return order_out(db, order_id)


@router.post("/{order_id}/unarchive", response_model=SalesOrderOut)
def unarchive_order(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    order = _get(db, order_id)
    order.archived_at = None
    db.commit()
    return order_out(db, order_id)


# ── Uppföljning ───────────────────────────────────────────────────────────────

@router.get("/{order_id}/notes", response_model=List[SalesLeadNoteOut])
def list_order_notes(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _notes_for(_get(db, order_id))


@router.post("/{order_id}/notes", response_model=SalesLeadNoteOut, status_code=status.HTTP_201_CREATED)
def add_order_note(
    order_id: int,
    body: SalesLeadNoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get(db, order_id)
    note = SalesLeadNote(
        order_id=order_id,
        note_date=body.note_date or date.today(),
        kind=body.kind,
        body=body.body,
        created_by=current_user.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _note_out(note)


@router.delete("/{order_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_note(
    order_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    # Bara orderns egna anteckningar – förfrågans logg tas bort på förfrågan
    note = db.query(SalesLeadNote).filter(
        SalesLeadNote.id == note_id, SalesLeadNote.order_id == order_id
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="Anteckning ej hittad")
    db.delete(note)
    db.commit()


# ── Schema och egna aktiviteter ───────────────────────────────────────────────

@router.get("/{order_id}/schedule", response_model=List[SalesScheduleItem])
def get_order_schedule(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Gantt-underlaget: sålddatum, avbockade milstolpar, AOC-intyg och
    leveransdatum som automatiska poster, plus egna aktiviteter."""
    return order_schedule(_get(db, order_id))


@router.get("/{order_id}/activities", response_model=List[SalesActivityOut])
def list_order_activities(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [activity_out(a) for a in _get(db, order_id).activities]


@router.post("/{order_id}/activities", response_model=SalesActivityOut, status_code=status.HTTP_201_CREATED)
def create_order_activity(
    order_id: int,
    body: SalesActivityCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    order = _get(db, order_id)
    data = body.model_dump()
    if data.get("sort_order") is None:
        data["sort_order"] = next_activity_sort(order.activities)
    activity = SalesActivity(order_id=order_id, **data)
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return activity_out(activity)


@router.put("/{order_id}/activities/{activity_id}", response_model=SalesActivityOut)
def update_order_activity(
    order_id: int,
    activity_id: int,
    body: SalesActivityUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    activity = db.query(SalesActivity).filter(
        SalesActivity.id == activity_id, SalesActivity.order_id == order_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Aktivitet ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(activity, field, value)
    db.commit()
    db.refresh(activity)
    return activity_out(activity)


@router.delete("/{order_id}/activities/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_activity(
    order_id: int,
    activity_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    activity = db.query(SalesActivity).filter(
        SalesActivity.id == activity_id, SalesActivity.order_id == order_id
    ).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Aktivitet ej hittad")
    db.delete(activity)
    db.commit()


@router.get("/{order_id}/pdf")
def order_pdf(order_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    order = _get(db, order_id)
    return StreamingResponse(
        build_order_pdf(order),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="order-{order_id}.pdf"'},
    )

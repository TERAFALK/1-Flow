"""Planeringsmöte – veckodokumentet som gås igenom med verkstaden.

Ersätter en Word-fil som skrevs om från grunden varje vecka. Poängen är att en
ny vecka utgår från den förra: jobben pågår över flera veckor, så raderna är
till stor del desamma och det som ändras är enstaka rader plus veckoschemat.

All veckoräkning görs här med ``date.isocalendar`` och ``date.fromisocalendar``.
Nyckeln är ISO-året och inte kalenderåret – vecka 1 2027 börjar 2026-12-28.
"""
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import (
    Customer, PlanningItemAssignee, PlanningMeeting, PlanningMeetingDay,
    PlanningMeetingItem, User, UserAbsence, WorkOrder, WorkOrderStatus,
)
from ..planning_pdf import build_planning_pdf
from ..schemas import (
    PlanningArchive, PlanningItemIn, PlanningItemOut, PlanningMeetingCreate,
    PlanningMeetingListItem, PlanningMeetingOut, PlanningMeetingUpdate,
    PlanningSuggestion,
)
from ..uploads import safe_filename

router = APIRouter(prefix="/api/planning-meetings", tags=["planning"])

# Arbete som fortfarande är i spel och därför kan höra hemma på ett möte
OPEN_WORK_STATUSES = (
    WorkOrderStatus.ny, WorkOrderStatus.planerad, WorkOrderStatus.pagaende,
)
# Statusar som gör en rad "klar att stryka" på nästa möte
DONE_WORK_STATUSES = (WorkOrderStatus.klar, WorkOrderStatus.fakturerad)


# ── Hjälpare ──────────────────────────────────────────────────────────────────

def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _load(db: Session, meeting_id: int) -> PlanningMeeting:
    meeting = (
        db.query(PlanningMeeting)
        .options(
            joinedload(PlanningMeeting.days),
            joinedload(PlanningMeeting.items).joinedload(PlanningMeetingItem.customer),
            joinedload(PlanningMeeting.items).joinedload(PlanningMeetingItem.work_order),
            joinedload(PlanningMeeting.items)
            .joinedload(PlanningMeetingItem.assignees)
            .joinedload(PlanningItemAssignee.user),
        )
        .filter(PlanningMeeting.id == meeting_id)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail="Veckan finns inte")
    return meeting


def _item_out(item: PlanningMeetingItem) -> PlanningItemOut:
    """Arbetsorderns status härleds vid läsning och sparas aldrig på raden – en
    order kan bli klar mitt i veckan och raden ska följa med direkt."""
    work_order = item.work_order
    status_value = work_order.status.value if work_order and work_order.status else None
    return PlanningItemOut(
        id=item.id,
        sort_order=item.sort_order or 0,
        customer_id=item.customer_id,
        # Kundkortet går före ögonblicksbilden så länge kunden finns kvar
        customer_text=(item.customer.name if item.customer else item.customer_text),
        work_order_id=item.work_order_id,
        description=item.description,
        done=bool(item.done),
        assignee_ids=[a.user_id for a in item.assignees],
        assignee_names=[a.user.full_name for a in item.assignees if a.user],
        work_order_number=work_order.order_number if work_order else None,
        work_order_status=status_value,
        work_order_done=bool(work_order and work_order.status in DONE_WORK_STATUSES),
    )


def _absences_for(db: Session, meeting: PlanningMeeting) -> list:
    """Frånvaro som överlappar veckan. Överlapp och inte "börjar i veckan" –
    en tvåveckorssemester ska synas båda veckorna."""
    week_end = meeting.monday_date + timedelta(days=6)
    return (
        db.query(UserAbsence)
        .options(joinedload(UserAbsence.user))
        .filter(UserAbsence.start_date <= week_end, UserAbsence.end_date >= meeting.monday_date)
        .order_by(UserAbsence.start_date, UserAbsence.id)
        .all()
    )


def _meeting_out(db: Session, meeting: PlanningMeeting) -> PlanningMeetingOut:
    from ..schemas import AbsenceOut

    items = sorted(meeting.items, key=lambda i: (i.sort_order or 0, i.id))
    out = [_item_out(i) for i in items]
    return PlanningMeetingOut(
        id=meeting.id,
        iso_year=meeting.iso_year,
        iso_week=meeting.iso_week,
        monday_date=meeting.monday_date,
        meeting_date=meeting.meeting_date,
        item_count=len(out),
        done_count=sum(1 for i in out if i.done),
        stale_count=sum(1 for i in out if i.work_order_done and not i.done),
        updated_at=meeting.updated_at,
        notes=meeting.notes,
        ffb_current=meeting.ffb_current,
        open_quotes=meeting.open_quotes,
        future_work=meeting.future_work,
        ffb_heading=meeting.ffb_heading,
        quotes_heading=meeting.quotes_heading,
        future_heading=meeting.future_heading,
        days=sorted(meeting.days, key=lambda d: (d.sort_order or 0, d.id)),
        items=out,
        absences=[
            AbsenceOut(
                id=a.id, user_id=a.user_id,
                user_name=a.user.full_name if a.user else "",
                start_date=a.start_date, end_date=a.end_date,
                kind=a.kind, note=a.note,
            )
            for a in _absences_for(db, meeting)
        ],
    )


def _set_assignees(db: Session, item: PlanningMeetingItem, user_ids: List[int]):
    """Ersätter radens ansvariga. Ordningen är betydelsefull – "DG/NF" läses i
    den ordning han skrev dem."""
    item.assignees.clear()
    db.flush()
    seen = set()
    for order, user_id in enumerate(user_ids or []):
        if user_id in seen:
            continue
        seen.add(user_id)
        item.assignees.append(PlanningItemAssignee(user_id=user_id, sort_order=order))


def _apply_item(db: Session, item: PlanningMeetingItem, body: PlanningItemIn):
    data = body.model_dump(exclude_unset=True)
    assignee_ids = data.pop("assignee_ids", None)
    for field, value in data.items():
        setattr(item, field, value)
    # Ögonblicksbild av kundnamnet, så raden går att läsa även om kunden raderas
    if item.customer_id:
        customer = db.get(Customer, item.customer_id)
        if customer:
            item.customer_text = customer.name
    if assignee_ids is not None:
        _set_assignees(db, item, assignee_ids)


# ── Arkiv och uppslag ─────────────────────────────────────────────────────────

@router.get("", response_model=PlanningArchive)
def list_meetings(
    limit: int = Query(60, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Arkivet plus veckan som knappen "Skapa vecka NN" ska sikta på.

    Nästa vecka räknas här och inte i webbläsaren: frontendens veckohjälpare ger
    bara veckonumret, inte ISO-året, och det är just årsskiftet som blir fel.
    """
    meetings = (
        db.query(PlanningMeeting)
        .order_by(PlanningMeeting.iso_year.desc(), PlanningMeeting.iso_week.desc())
        .limit(limit)
        .all()
    )

    counts = dict(
        db.query(PlanningMeetingItem.meeting_id, func.count(PlanningMeetingItem.id))
        .group_by(PlanningMeetingItem.meeting_id).all()
    )
    done = dict(
        db.query(PlanningMeetingItem.meeting_id, func.count(PlanningMeetingItem.id))
        .filter(PlanningMeetingItem.done.is_(True))
        .group_by(PlanningMeetingItem.meeting_id).all()
    )
    stale = dict(
        db.query(PlanningMeetingItem.meeting_id, func.count(PlanningMeetingItem.id))
        .join(WorkOrder, WorkOrder.id == PlanningMeetingItem.work_order_id)
        .filter(WorkOrder.status.in_(DONE_WORK_STATUSES), PlanningMeetingItem.done.is_(False))
        .group_by(PlanningMeetingItem.meeting_id).all()
    )

    latest = meetings[0] if meetings else None
    next_monday = _monday(latest.monday_date + timedelta(days=7)) if latest else _monday(date.today())
    if latest and next_monday <= _monday(date.today()):
        # Ligger arkivet efter siktar knappen på innevarande vecka i stället
        next_monday = _monday(date.today())
    iso_year, iso_week, _weekday = next_monday.isocalendar()

    return PlanningArchive(
        weeks=[
            PlanningMeetingListItem(
                id=m.id, iso_year=m.iso_year, iso_week=m.iso_week,
                monday_date=m.monday_date, meeting_date=m.meeting_date,
                item_count=counts.get(m.id, 0), done_count=done.get(m.id, 0),
                stale_count=stale.get(m.id, 0), updated_at=m.updated_at,
            )
            for m in meetings
        ],
        next_year=iso_year, next_week=iso_week, next_monday=next_monday,
    )


# Måste ligga före /{meeting_id}, annars matchas "by-week" mot en int och ger 422
@router.get("/by-week/{iso_year}/{iso_week}", response_model=PlanningMeetingOut)
def get_by_week(
    iso_year: int, iso_week: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    meeting = (
        db.query(PlanningMeeting)
        .filter(PlanningMeeting.iso_year == iso_year, PlanningMeeting.iso_week == iso_week)
        .first()
    )
    if not meeting:
        raise HTTPException(status_code=404, detail=f"Vecka {iso_week} finns inte")
    return _meeting_out(db, _load(db, meeting.id))


@router.get("/{meeting_id}", response_model=PlanningMeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _meeting_out(db, _load(db, meeting_id))


# ── Skapa vecka ───────────────────────────────────────────────────────────────

@router.post("", response_model=PlanningMeetingOut, status_code=status.HTTP_201_CREATED)
def create_meeting(
    body: PlanningMeetingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Skapar veckan, eventuellt som en kopia av en tidigare.

    Finns veckan redan svarar den 409 med id:t – att tyst returnera den
    befintliga veckan hade sett ut som att kopieringen gjordes.
    """
    source = db.get(PlanningMeeting, body.copy_from_id) if body.copy_from_id else None
    if body.copy_from_id and not source:
        raise HTTPException(status_code=404, detail="Veckan att kopiera från finns inte")

    if body.monday:
        monday = _monday(body.monday)
    elif source:
        monday = source.monday_date + timedelta(days=7)
    else:
        monday = _monday(date.today())

    iso_year, iso_week, _weekday = monday.isocalendar()
    existing = (
        db.query(PlanningMeeting)
        .filter(PlanningMeeting.iso_year == iso_year, PlanningMeeting.iso_week == iso_week)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "message": f"Vecka {iso_week} finns redan",
                "existing_id": existing.id,
                "iso_year": iso_year,
                "iso_week": iso_week,
            },
        )

    copy = body.copy
    meeting = PlanningMeeting(
        monday_date=monday, iso_year=iso_year, iso_week=iso_week,
        meeting_date=monday,
        created_by=current_user.id,
        notes=source.notes if (source and copy.notes) else None,
        ffb_current=source.ffb_current if (source and copy.sections) else None,
        open_quotes=source.open_quotes if (source and copy.sections) else None,
        future_work=source.future_work if (source and copy.sections) else None,
        ffb_heading=(source.ffb_heading if source else None) or "Aktuellt FFB",
        quotes_heading=(source.quotes_heading if source else None) or "Pågående offerter",
        future_heading=(source.future_heading if source else None) or "Kommande arbete",
    )

    # Mån–Fre skapas alltid, så formuläret alltid har fem rader att fylla i
    old_days = {d.day_date.weekday(): d.text for d in source.days} if (source and copy.days) else {}
    for index in range(5):
        meeting.days.append(PlanningMeetingDay(
            day_date=monday + timedelta(days=index),
            text=old_days.get(index),
            sort_order=index,
        ))

    if source and copy.items:
        # Avbockade rader följer inte med – det är så listan städar sig själv
        carried = sorted(
            (i for i in source.items if not i.done),
            key=lambda i: (i.sort_order or 0, i.id),
        )
        for order, old in enumerate(carried):
            item = PlanningMeetingItem(
                sort_order=order,
                customer_id=old.customer_id,
                customer_text=old.customer_text,
                work_order_id=old.work_order_id,
                description=old.description,
                done=False,
            )
            for a in sorted(old.assignees, key=lambda a: a.sort_order or 0):
                item.assignees.append(
                    PlanningItemAssignee(user_id=a.user_id, sort_order=a.sort_order or 0)
                )
            meeting.items.append(item)

    db.add(meeting)
    try:
        db.commit()
    except IntegrityError:
        # Två som skapar samma vecka samtidigt – unikhetsvillkoret avgör
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Vecka {iso_week} finns redan")
    return _meeting_out(db, _load(db, meeting.id))


@router.put("/{meeting_id}", response_model=PlanningMeetingOut)
def update_meeting(
    meeting_id: int,
    body: PlanningMeetingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Veckoschemat och de fyra fritextfälten i ett anrop – de sparas
    tillsammans från formuläret."""
    meeting = _load(db, meeting_id)
    data = body.model_dump(exclude_unset=True)
    days = data.pop("days", None)
    for field, value in data.items():
        setattr(meeting, field, value)

    if days is not None:
        by_date = {d.day_date: d for d in meeting.days}
        for order, day in enumerate(days):
            existing = by_date.get(day["day_date"])
            if existing:
                existing.text = day.get("text")
            else:
                meeting.days.append(PlanningMeetingDay(
                    day_date=day["day_date"], text=day.get("text"), sort_order=order,
                ))

    db.commit()
    return _meeting_out(db, _load(db, meeting_id))


@router.delete("/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    db.delete(_load(db, meeting_id))
    db.commit()


# ── Rader ─────────────────────────────────────────────────────────────────────

@router.post("/{meeting_id}/items", response_model=PlanningItemOut, status_code=status.HTTP_201_CREATED)
def create_item(
    meeting_id: int,
    body: PlanningItemIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    meeting = _load(db, meeting_id)
    last = max((i.sort_order or 0 for i in meeting.items), default=-1)
    item = PlanningMeetingItem(meeting_id=meeting.id, sort_order=last + 1)
    db.add(item)
    db.flush()
    _apply_item(db, item, body)
    db.commit()
    db.refresh(item)
    return _item_out(item)


# Före /{item_id}: annars matchas "reorder" mot item_id: int och ger 422
@router.put("/{meeting_id}/items/reorder", response_model=List[PlanningItemOut])
def reorder_items(
    meeting_id: int,
    order: List[int],
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    meeting = _load(db, meeting_id)
    positions = {item_id: index for index, item_id in enumerate(order)}
    for item in meeting.items:
        if item.id in positions:
            item.sort_order = positions[item.id]
    db.commit()
    meeting = _load(db, meeting_id)
    return [_item_out(i) for i in sorted(meeting.items, key=lambda i: (i.sort_order or 0, i.id))]


@router.put("/{meeting_id}/items/{item_id}", response_model=PlanningItemOut)
def update_item(
    meeting_id: int, item_id: int,
    body: PlanningItemIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    item = (
        db.query(PlanningMeetingItem)
        .filter(PlanningMeetingItem.id == item_id, PlanningMeetingItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Raden finns inte")
    _apply_item(db, item, body)
    db.commit()
    db.refresh(item)
    return _item_out(item)


@router.delete("/{meeting_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    meeting_id: int, item_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    item = (
        db.query(PlanningMeetingItem)
        .filter(PlanningMeetingItem.id == item_id, PlanningMeetingItem.meeting_id == meeting_id)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Raden finns inte")
    db.delete(item)
    db.commit()


# ── Förslag ───────────────────────────────────────────────────────────────────

@router.get("/{meeting_id}/suggestions", response_model=List[PlanningSuggestion])
def suggestions(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Öppna arbetsordrar som aldrig förekommit på något planeringsmöte.

    "Aldrig på något möte" och inte "inte på förra mötet": en order han medvetet
    valt bort ska inte föreslås igen varje vecka. Frågan är idempotent och kräver
    ingen bokföring av vad som redan visats.
    """
    _load(db, meeting_id)
    used = db.query(PlanningMeetingItem.work_order_id).filter(
        PlanningMeetingItem.work_order_id.isnot(None)
    )
    orders = (
        db.query(WorkOrder)
        .options(joinedload(WorkOrder.customer))
        .filter(WorkOrder.status.in_(OPEN_WORK_STATUSES), WorkOrder.id.notin_(used))
        .order_by(WorkOrder.created_at.desc())
        .all()
    )
    return [
        PlanningSuggestion(
            work_order_id=o.id,
            order_number=o.order_number,
            customer_id=o.customer_id,
            customer_name=o.customer.name if o.customer else "",
            description=o.description or "",
            assignee_ids=[o.assigned_to] if o.assigned_to else [],
            status=o.status.value if o.status else "",
        )
        for o in orders
    ]


# ── Utskrift ──────────────────────────────────────────────────────────────────

@router.get("/{meeting_id}/pdf")
def meeting_pdf(meeting_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    meeting = _load(db, meeting_id)
    items = sorted(meeting.items, key=lambda i: (i.sort_order or 0, i.id))
    filename = safe_filename(f"Planering-v{meeting.iso_week}-{meeting.iso_year}") + ".pdf"
    return StreamingResponse(
        build_planning_pdf(meeting, items, _absences_for(db, meeting)),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

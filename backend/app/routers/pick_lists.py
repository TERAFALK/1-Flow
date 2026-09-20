import io
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from ..database import get_db
from ..deps import get_current_user
from ..schemas import (
    PickListCreate, PickListUpdate, PickListOut, PickListListItem,
    PickListLineCreate, PickListLineUpdate, PickListLineOut, PickListScanResult,
    LineQuantityUpdate,
)
from ..models import PickList, PickListLine, Article, User, UserRole
from ..pdf_utils import draw_header

router = APIRouter(prefix="/api/pick-lists", tags=["pick-lists"])

# Teknikerns tillfälliga skanningar. Adminens egna plock har kind "plocklista".
SCAN_KIND = "skanning"


def _out(pl: PickList) -> PickListOut:
    return PickListOut(
        id=pl.id, title=pl.title, notes=pl.notes, kind=pl.kind,
        created_at=pl.created_at, closed_at=pl.closed_at,
        created_by=pl.created_by,
        created_by_name=pl.creator.full_name if pl.creator else None,
        lines=[PickListLineOut.from_line(l) for l in pl.lines],
    )


def _with_article_number(db: Session, data: dict) -> dict:
    """Snapshotar art.nr på plockraden så det överlever en ominläsning av artikelregistret."""
    if not data.get("article_number") and data.get("article_id"):
        article = db.get(Article, data["article_id"])
        if article:
            data["article_number"] = article.article_number
    return data


def _get(db: Session, pick_list_id: int) -> PickList:
    pl = (
        db.query(PickList)
        .options(joinedload(PickList.lines).joinedload(PickListLine.article))
        .filter(PickList.id == pick_list_id)
        .first()
    )
    if not pl:
        raise HTTPException(status_code=404, detail="Plocklista ej hittad")
    return pl


def _get_for_user(db: Session, pick_list_id: int, user: User) -> PickList:
    """Som ``_get``, men släpper bara fram teknikern till skanningarna.

    Allowlisten i deps.py styr vilka *vägar* en tekniker når, aldrig vilka rader.
    Utan den här kontrollen kan en teknikertoken öppna, döpa om och skanna in i
    vilken av adminens plocklistor som helst genom att gissa ett id.
    """
    pl = _get(db, pick_list_id)
    if user.role == UserRole.tekniker and pl.kind != SCAN_KIND:
        raise HTTPException(status_code=403, detail="Åtkomst nekad för teknikerkonto")
    return pl


@router.get("", response_model=List[PickListListItem])
def list_pick_lists(
    kind: Optional[str] = None,
    include_closed: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Listar plocklistor och skanningar. Öppna först, därefter senast skapad.

    En tekniker får bara skanningar oavsett vad som efterfrågas – det är den
    regeln som gör att listningen kan vara öppen för teknikerkonton utan att
    adminens plocklistor läcker ut i skannern.
    """
    if current_user.role == UserRole.tekniker:
        kind = SCAN_KIND

    q = db.query(PickList).options(joinedload(PickList.lines), joinedload(PickList.creator))
    if kind:
        q = q.filter(PickList.kind == kind)
    if not include_closed:
        q = q.filter(PickList.closed_at.is_(None))
    lists = q.order_by(
        PickList.closed_at.is_(None).desc(), PickList.created_at.desc()
    ).all()
    return [
        PickListListItem(
            id=p.id, title=p.title, notes=p.notes, kind=p.kind,
            created_at=p.created_at, closed_at=p.closed_at,
            created_by=p.created_by,
            created_by_name=p.creator.full_name if p.creator else None,
            line_count=len(p.lines),
        )
        for p in lists
    ]


@router.post("", response_model=PickListOut, status_code=status.HTTP_201_CREATED)
def create_pick_list(body: PickListCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    kind = body.kind if body.kind in ("plocklista", SCAN_KIND) else "plocklista"
    # En tekniker skapar bara skanningar, aldrig en plocklista i adminens vy
    if current_user.role == UserRole.tekniker:
        kind = SCAN_KIND
    pl = PickList(title=body.title, notes=body.notes, kind=kind, created_by=current_user.id)
    db.add(pl)
    db.flush()
    for line in body.lines:
        db.add(PickListLine(pick_list_id=pl.id, **_with_article_number(db, line.model_dump())))
    db.commit()
    return _out(_get(db, pl.id))


@router.get("/{pick_list_id}", response_model=PickListOut)
def get_pick_list(pick_list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _out(_get_for_user(db, pick_list_id, current_user))


@router.put("/{pick_list_id}", response_model=PickListOut)
def update_pick_list(pick_list_id: int, body: PickListUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pl = _get_for_user(db, pick_list_id, current_user)
    data = body.model_dump(exclude_unset=True)
    # closed är ett ja/nej utåt men en tidsstämpel i databasen, så den måste
    # plockas ur innan resten sätts rakt av
    if "closed" in data:
        closed = data.pop("closed")
        pl.closed_at = datetime.utcnow() if closed else None
    for field, value in data.items():
        setattr(pl, field, value)
    db.commit()
    return _out(_get(db, pick_list_id))


@router.delete("/{pick_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pick_list(pick_list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pl = _get_for_user(db, pick_list_id, current_user)
    db.delete(pl)
    db.commit()


@router.post("/{pick_list_id}/lines", response_model=PickListLineOut, status_code=status.HTTP_201_CREATED)
def add_line(pick_list_id: int, body: PickListLineCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(PickList, pick_list_id):
        raise HTTPException(status_code=404, detail="Plocklista ej hittad")
    line = PickListLine(pick_list_id=pick_list_id, **_with_article_number(db, body.model_dump()))
    db.add(line)
    db.commit()
    db.refresh(line)
    line = db.query(PickListLine).options(joinedload(PickListLine.article)).get(line.id)
    return PickListLineOut.from_line(line)


@router.put("/{pick_list_id}/lines/{line_id}", response_model=PickListLineOut)
def update_line(pick_list_id: int, line_id: int, body: PickListLineUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    line = db.query(PickListLine).filter(PickListLine.id == line_id, PickListLine.pick_list_id == pick_list_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Rad ej hittad")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(line, field, value)
    db.commit()
    line = db.query(PickListLine).options(joinedload(PickListLine.article)).get(line_id)
    return PickListLineOut.from_line(line)


@router.delete("/{pick_list_id}/lines/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(pick_list_id: int, line_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    line = db.query(PickListLine).filter(PickListLine.id == line_id, PickListLine.pick_list_id == pick_list_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Rad ej hittad")
    db.delete(line)
    db.commit()


@router.put("/{pick_list_id}/lines/{line_id}/quantity", response_model=Optional[PickListLineOut])
def set_scanned_quantity(
    pick_list_id: int,
    line_id: int,
    body: LineQuantityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rättar antalet på en skannad rad. 0 tar bort raden.

    En egen väg och inte ``update_line``, så att teknikern bara får ändra antal
    och ta bort – inte skriva om beskrivning eller enhet. Plocklistor drar inte
    från lagret, så här finns inget saldo att justera.
    """
    if body.quantity < 0:
        raise HTTPException(status_code=400, detail="Antalet kan inte vara negativt")
    _get_for_user(db, pick_list_id, current_user)
    line = db.query(PickListLine).filter(
        PickListLine.id == line_id, PickListLine.pick_list_id == pick_list_id
    ).first()
    if not line:
        raise HTTPException(status_code=404, detail="Rad ej hittad")

    if body.quantity == 0:
        db.delete(line)
        db.commit()
        return None

    line.quantity = body.quantity
    db.commit()
    line = db.query(PickListLine).options(joinedload(PickListLine.article)).get(line_id)
    return PickListLineOut.from_line(line)


@router.post("/{pick_list_id}/scan", response_model=PickListScanResult)
def scan_into_pick_list(
    pick_list_id: int,
    barcode: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pl = _get_for_user(db, pick_list_id, current_user)
    if pl.closed_at:
        raise HTTPException(status_code=400, detail="Skanningen är avslutad – öppna den igen först")

    article = db.query(Article).filter(
        (Article.barcode == barcode) | (Article.article_number == barcode)
    ).first()

    if article:
        line = db.query(PickListLine).filter(
            PickListLine.pick_list_id == pick_list_id,
            PickListLine.article_id == article.id,
        ).first()
        if line:
            line.quantity = line.quantity + Decimal("1")
            if not line.article_number:
                line.article_number = article.article_number
        else:
            line = PickListLine(
                pick_list_id=pick_list_id,
                article_id=article.id,
                article_number=article.article_number,
                description=article.name,
                quantity=Decimal("1"),
                unit=article.unit,
                location=article.location,
            )
            db.add(line)
        db.commit()
        db.refresh(line)
        line = db.query(PickListLine).options(joinedload(PickListLine.article)).get(line.id)
        return PickListScanResult(article_name=article.name, line=PickListLineOut.from_line(line), unknown=False)
    else:
        desc = f"Okänd ({barcode})"
        line = db.query(PickListLine).filter(
            PickListLine.pick_list_id == pick_list_id,
            PickListLine.article_id.is_(None),
            PickListLine.description == desc,
        ).first()
        if line:
            line.quantity = line.quantity + Decimal("1")
        else:
            line = PickListLine(
                pick_list_id=pick_list_id,
                article_id=None,
                # Skannad kod sparas som art.nr så raden hittar tillbaka vid import
                article_number=barcode,
                description=desc,
                quantity=Decimal("1"),
                unit="st",
            )
            db.add(line)
        db.commit()
        db.refresh(line)
        return PickListScanResult(article_name=desc, line=PickListLineOut.from_line(line), unknown=True)


@router.get("/{pick_list_id}/pdf")
def pick_list_pdf(pick_list_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pl = _get_for_user(db, pick_list_id, current_user)
    # Samma PDF för båda sorterna, men rubriken ska stämma med vad man skrev ut
    heading = "Skanning" if pl.kind == SCAN_KIND else "Plocklista"

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    y = draw_header(c, page_w, heading, pl.title)
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(margin, y, f"Skapad: {pl.created_at.strftime('%Y-%m-%d %H:%M')}")
    if pl.notes:
        c.drawString(margin, y - 12, f"Anteckning: {pl.notes}")
        y -= 12
    c.setFillColor(colors.black)
    y -= 20

    col_x = {
        "check": margin,
        "art": margin + 9 * mm,
        "desc": margin + 34 * mm,
        "loc": margin + 96 * mm,
        "qty": margin + 112 * mm,
        "unit": margin + 122 * mm,
        "rest": margin + 136 * mm,
        "levererat": margin + 156 * mm,
    }

    def header_row(yy):
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.HexColor("#1a1a1a"))
        c.rect(margin, yy - 14, page_w - 2 * margin, 16, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.drawString(col_x["check"] + 2, yy - 10, "☐")
        c.drawString(col_x["art"], yy - 10, "Art.nr")
        c.drawString(col_x["desc"], yy - 10, "Artikel")
        c.drawString(col_x["loc"], yy - 10, "Plats")
        c.drawString(col_x["qty"], yy - 10, "Antal")
        c.drawString(col_x["unit"], yy - 10, "Enhet")
        c.drawString(col_x["rest"], yy - 10, "Rest")
        c.drawString(col_x["levererat"], yy - 10, "Levererat")
        c.setFillColor(colors.black)
        return yy - 18

    y = header_row(y)
    c.setFont("Helvetica", 8.5)
    row_h = 16
    for line in pl.lines:
        if y < 25 * mm:
            c.showPage()
            y = draw_header(c, page_w, heading, pl.title)
            y -= 10
            y = header_row(y)
            c.setFont("Helvetica", 8.5)
        c.rect(col_x["check"], y - 9, 9, 9, stroke=1, fill=0)
        art_nr = line.article_number or (line.article.article_number if line.article else "")
        c.drawString(col_x["art"], y - 8, (art_nr or "")[:12])
        c.drawString(col_x["desc"], y - 8, (line.description or "")[:34])
        c.drawString(col_x["loc"], y - 8, (line.location or "")[:8])
        c.drawRightString(col_x["unit"] - 3, y - 8, f"{float(line.quantity):g}")
        c.drawString(col_x["unit"], y - 8, line.unit or "st")
        # blank handwriting lines for "Rest" / "Levererat"
        c.setStrokeColor(colors.HexColor("#999999"))
        c.line(col_x["rest"], y - 12, col_x["levererat"] - 4 * mm, y - 12)
        c.line(col_x["levererat"], y - 12, page_w - margin, y - 12)
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.line(margin, y - row_h + 2, page_w - margin, y - row_h + 2)
        c.setStrokeColor(colors.black)
        y -= row_h

    c.save()
    buf.seek(0)
    filename = f"{heading.lower()}-{pl.id}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

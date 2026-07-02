import io
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
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
    PickListLineCreate, PickListLineUpdate, PickListLineOut,
)
from ..models import PickList, PickListLine, Article, User
from ..pdf_utils import draw_header

router = APIRouter(prefix="/api/pick-lists", tags=["pick-lists"])


def _out(pl: PickList) -> PickListOut:
    return PickListOut(
        id=pl.id, title=pl.title, notes=pl.notes, created_at=pl.created_at,
        lines=[PickListLineOut.from_line(l) for l in pl.lines],
    )


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


@router.get("", response_model=List[PickListListItem])
def list_pick_lists(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    lists = db.query(PickList).options(joinedload(PickList.lines)).order_by(PickList.created_at.desc()).all()
    return [
        PickListListItem(id=p.id, title=p.title, notes=p.notes, created_at=p.created_at, line_count=len(p.lines))
        for p in lists
    ]


@router.post("", response_model=PickListOut, status_code=status.HTTP_201_CREATED)
def create_pick_list(body: PickListCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pl = PickList(title=body.title, notes=body.notes, created_by=current_user.id)
    db.add(pl)
    db.flush()
    for line in body.lines:
        db.add(PickListLine(pick_list_id=pl.id, **line.model_dump()))
    db.commit()
    return _out(_get(db, pl.id))


@router.get("/{pick_list_id}", response_model=PickListOut)
def get_pick_list(pick_list_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _out(_get(db, pick_list_id))


@router.put("/{pick_list_id}", response_model=PickListOut)
def update_pick_list(pick_list_id: int, body: PickListUpdate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    pl = _get(db, pick_list_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(pl, field, value)
    db.commit()
    return _out(_get(db, pick_list_id))


@router.delete("/{pick_list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pick_list(pick_list_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    pl = db.get(PickList, pick_list_id)
    if not pl:
        raise HTTPException(status_code=404, detail="Plocklista ej hittad")
    db.delete(pl)
    db.commit()


@router.post("/{pick_list_id}/lines", response_model=PickListLineOut, status_code=status.HTTP_201_CREATED)
def add_line(pick_list_id: int, body: PickListLineCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    if not db.get(PickList, pick_list_id):
        raise HTTPException(status_code=404, detail="Plocklista ej hittad")
    line = PickListLine(pick_list_id=pick_list_id, **body.model_dump())
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
    for field, value in body.model_dump(exclude_none=True).items():
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


@router.get("/{pick_list_id}/pdf")
def pick_list_pdf(pick_list_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    pl = _get(db, pick_list_id)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 18 * mm

    y = draw_header(c, page_w, "Plocklista", pl.title)
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
            y = draw_header(c, page_w, "Plocklista", pl.title)
            y -= 10
            y = header_row(y)
            c.setFont("Helvetica", 8.5)
        c.rect(col_x["check"], y - 9, 9, 9, stroke=1, fill=0)
        art_nr = line.article.article_number if line.article else ""
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
    filename = f"plocklista-{pl.id}.pdf"
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

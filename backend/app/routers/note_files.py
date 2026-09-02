"""Bilagor på en enskild anteckning.

Rutten är generisk mot anteckningen och inte mot dess förälder, så samma
endpoints fungerar oavsett om anteckningen sitter på en kund, en förfrågan eller
en såld order. Idag används den från kundens aktivitetsflik.
"""
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import require_admin
from ..models import SalesLeadNote, SalesLeadFile, User
from ..schemas import SalesLeadFileOut
from ..uploads import store_file, file_path, remove_file

router = APIRouter(prefix="/api/notes", tags=["note-files"])

# Egen mapp på samma uploads-volym som övriga bilagor
UPLOAD_ROOT = "/app/uploads/crm-notes"


def _get_note(db: Session, note_id: int) -> SalesLeadNote:
    note = (
        db.query(SalesLeadNote)
        .options(joinedload(SalesLeadNote.files))
        .filter(SalesLeadNote.id == note_id)
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Anteckning ej hittad")
    return note


def _get_file(db: Session, note_id: int, file_id: int) -> SalesLeadFile:
    record = db.query(SalesLeadFile).filter(
        SalesLeadFile.id == file_id, SalesLeadFile.note_id == note_id
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail="Fil ej hittad")
    return record


@router.get("/{note_id}/files", response_model=List[SalesLeadFileOut])
def list_note_files(note_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _get_note(db, note_id).files


@router.post("/{note_id}/files", response_model=SalesLeadFileOut, status_code=status.HTTP_201_CREATED)
async def upload_note_file(
    note_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    _get_note(db, note_id)
    content = await file.read()
    stored_name = store_file(UPLOAD_ROOT, note_id, file.filename or "", content)

    record = SalesLeadFile(
        note_id=note_id,
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


@router.get("/{note_id}/files/{file_id}/download")
def download_note_file(
    note_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = _get_file(db, note_id, file_id)
    path = file_path(UPLOAD_ROOT, note_id, record.filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Fil saknas på disk")
    return FileResponse(
        path,
        filename=record.original_name,
        media_type=record.mime_type or "application/octet-stream",
    )


@router.delete("/{note_id}/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note_file(
    note_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    record = _get_file(db, note_id, file_id)
    remove_file(UPLOAD_ROOT, note_id, record.filename)
    db.delete(record)
    db.commit()

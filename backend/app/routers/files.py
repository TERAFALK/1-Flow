import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import WorkOrderFile, WorkOrder, User, FileType
from ..schemas import WorkOrderFileOut

router = APIRouter(prefix="/api/work-orders", tags=["files"])

UPLOAD_ROOT = "/app/uploads"

ALLOWED_TYPES = {
    "document": {"application/pdf", "application/msword",
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                 "application/vnd.ms-excel",
                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                 "text/plain"},
    "photo":    {"image/jpeg", "image/png", "image/webp", "image/gif", "image/tiff"},
    "drawing":  {"application/pdf", "application/acad", "image/vnd.dwg",
                 "application/dxf", "application/octet-stream"},
}


@router.get("/{order_id}/files", response_model=List[WorkOrderFileOut])
def list_files(
    order_id: int,
    file_type: FileType = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")
    q = db.query(WorkOrderFile).filter(WorkOrderFile.work_order_id == order_id)
    if file_type:
        q = q.filter(WorkOrderFile.file_type == file_type)
    return q.order_by(WorkOrderFile.uploaded_at.desc()).all()


@router.post("/{order_id}/files", response_model=WorkOrderFileOut, status_code=201)
async def upload_file(
    order_id: int,
    file_type: FileType = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not db.get(WorkOrder, order_id):
        raise HTTPException(404, "Arbetsorder ej hittad")

    ext = os.path.splitext(file.filename or "")[1].lower()
    stored_name = f"{uuid.uuid4()}{ext}"
    folder = os.path.join(UPLOAD_ROOT, str(order_id))
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, stored_name)

    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    record = WorkOrderFile(
        work_order_id=order_id,
        filename=stored_name,
        original_name=file.filename or stored_name,
        file_type=file_type,
        mime_type=file.content_type,
        size_bytes=len(content),
        uploaded_by=current_user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@router.get("/{order_id}/files/{file_id}/download")
def download_file(
    order_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = db.query(WorkOrderFile).filter(
        WorkOrderFile.id == file_id,
        WorkOrderFile.work_order_id == order_id,
    ).first()
    if not record:
        raise HTTPException(404, "Fil ej hittad")
    path = os.path.join(UPLOAD_ROOT, str(order_id), record.filename)
    if not os.path.exists(path):
        raise HTTPException(404, "Fil saknas på disk")
    return FileResponse(path, filename=record.original_name, media_type=record.mime_type or "application/octet-stream")


@router.delete("/{order_id}/files/{file_id}", status_code=204)
def delete_file(
    order_id: int,
    file_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    record = db.query(WorkOrderFile).filter(
        WorkOrderFile.id == file_id,
        WorkOrderFile.work_order_id == order_id,
    ).first()
    if not record:
        raise HTTPException(404, "Fil ej hittad")
    path = os.path.join(UPLOAD_ROOT, str(order_id), record.filename)
    if os.path.exists(path):
        os.remove(path)
    db.delete(record)
    db.commit()

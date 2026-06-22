from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_user
from ..models import Settings, User
from ..schemas import SettingOut, SettingUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {
    "order_number_mode": "auto",
    "purchase_number_mode": "auto",
}


def _ensure_defaults(db: Session):
    for key, value in DEFAULTS.items():
        if not db.get(Settings, key):
            db.add(Settings(key=key, value=value))
    db.commit()


@router.get("", response_model=List[SettingOut])
def get_settings(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _ensure_defaults(db)
    return db.query(Settings).all()


@router.put("/{key}", response_model=SettingOut)
def update_setting(
    key: str,
    body: SettingUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    _ensure_defaults(db)
    s = db.get(Settings, key)
    if not s:
        s = Settings(key=key, value=body.value)
        db.add(s)
    else:
        s.value = body.value
    db.commit()
    db.refresh(s)
    return s

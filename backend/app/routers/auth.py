import time
from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..auth import verify_password, create_access_token, TECHNICIAN_TOKEN_EXPIRE_HOURS
from ..schemas import (
    LoginRequest, Token, UserOut, TechnicianOption, TechnicianLoginRequest,
)
from .. import models

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Bromsning av lösenordsgissning ────────────────────────────────────────────
# Teknikerlösenord har inget komplexitetskrav och teknikerlistan är publik, så
# inloggningen behöver ett tak för antal försök. Backend körs som en enda
# uvicorn-process (ingen --workers), därför räcker en modullokal dict.
# Nyckeln är kontot, inte IP: hela verkstaden delar utgående adress och skulle
# annars låsas ute så fort en person slinter.

_MAX_FAILS = 8
_WINDOW = 300.0  # sekunder – både mätfönster och utelåsningstid
_fails: dict[str, list[float]] = {}


def _prune(key: str, now: float) -> list[float]:
    stamps = [t for t in _fails.get(key, []) if now - t < _WINDOW]
    if stamps:
        _fails[key] = stamps
    else:
        _fails.pop(key, None)
    return stamps


def _throttle_check(key: str) -> None:
    now = time.monotonic()
    if len(_fails) > 1000:  # håll dicten bunden
        for k in list(_fails):
            _prune(k, now)
    if len(_prune(key, now)) >= _MAX_FAILS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="För många misslyckade försök. Försök igen om några minuter.",
        )


def _throttle_fail(key: str) -> None:
    _fails.setdefault(key, []).append(time.monotonic())


def _throttle_reset(key: str) -> None:
    _fails.pop(key, None)


# ── Inloggning ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    key = f"e:{req.email.strip().lower()}"
    _throttle_check(key)
    user = db.query(models.User).filter(models.User.email == req.email).first()
    if not user or not verify_password(req.password, user.hashed_password):
        _throttle_fail(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Felaktig e-post eller lösenord",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kontot är inaktiverat")
    _throttle_reset(key)
    token = create_access_token({"sub": user.id})
    return Token(access_token=token, user=UserOut.model_validate(user))


@router.get("/technicians", response_model=List[TechnicianOption])
def list_technicians(db: Session = Depends(get_db)):
    """Publik lista som fyller teknikerväljaren på inloggningsskärmen.

    Endpointen kräver ingen inloggning – den måste kunna läsas innan man loggat
    in. Svarsmodellen begränsar utdatan till id och namn, så e-post, roll och
    lösenordshash kan inte läcka härifrån. Administratörer utelämnas helt.
    """
    return (
        db.query(models.User)
        .filter(
            models.User.role == models.UserRole.tekniker,
            models.User.is_active.is_(True),
        )
        .order_by(models.User.full_name)
        .all()
    )


@router.post("/login-technician", response_model=Token)
def login_technician(req: TechnicianLoginRequest, db: Session = Depends(get_db)):
    """Inloggning via teknikerväljaren: vald tekniker + lösenord.

    Rollkontrollen nedan är det som gör att endpointen aldrig kan utfärda en
    admin-token, även om någon känner till ett adminkontos id och lösenord.
    """
    key = f"t:{req.user_id}"
    _throttle_check(key)
    user = db.get(models.User, req.user_id)
    # Samma svar oavsett orsak – ingen enumerering av konton eller roller
    if (
        not user
        or user.role != models.UserRole.tekniker
        or not user.is_active
        or not verify_password(req.password, user.hashed_password)
    ):
        _throttle_fail(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Felaktigt lösenord",
        )
    _throttle_reset(key)
    token = create_access_token(
        {"sub": user.id},
        expires_delta=timedelta(hours=TECHNICIAN_TOKEN_EXPIRE_HOURS),
    )
    return Token(access_token=token, user=UserOut.model_validate(user))

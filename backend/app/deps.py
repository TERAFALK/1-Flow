import re
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from .database import get_db
from .auth import decode_token
from . import models

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ── Teknikerns tillåtna API-yta ───────────────────────────────────────────────
# En tekniker kommer bara åt scannersidan i gränssnittet, men frontend-spärren i
# app.js är bara kosmetisk – utan kontrollen nedan når en teknikertoken hela
# API:et. Listan speglar exakt anropen i frontend/src/js/pages/scanner.js plus
# /api/users/me som app.js gör vid uppstart och sessionsåterställning.
#
# Listan är avsiktligt fail-closed: en ny endpoint är stängd för tekniker tills
# någon aktivt lägger till den här.
_TEKNIKER_ALLOWLIST: tuple[tuple[str, re.Pattern], ...] = (
    ("GET",  re.compile(r"^/api/users/me$")),
    ("GET",  re.compile(r"^/api/work-orders$")),
    ("GET",  re.compile(r"^/api/work-orders/\d+/lines$")),
    ("POST", re.compile(r"^/api/work-orders/\d+/scan$")),
    ("POST", re.compile(r"^/api/pick-lists$")),
    ("GET",  re.compile(r"^/api/pick-lists/\d+$")),
    ("POST", re.compile(r"^/api/pick-lists/\d+/scan$")),
    ("GET",  re.compile(r"^/api/pick-lists/\d+/pdf$")),
)


def _tekniker_may_access(method: str, path: str) -> bool:
    # FastAPI:s APIRoute registrerar inte HEAD automatiskt, så ett HEAD-anrop ger
    # 405 redan vid routing. Normaliseringen finns för att en rutt som någon gång
    # deklarerar HEAD explicit inte ska smita förbi listan.
    if method == "HEAD":
        method = "GET"
    return any(m == method and rx.match(path) for m, rx in _TEKNIKER_ALLOWLIST)


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ogiltig eller utgången session",
        )
    user = db.query(models.User).filter(models.User.id == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Användare ej hittad")

    # Rollspärren ligger här eftersom varje skyddad endpoint redan beror på den
    # här funktionen – direkt eller via require_admin. Publika endpoints (login,
    # health) gör det inte och påverkas därför inte.
    if user.role == models.UserRole.tekniker and not _tekniker_may_access(
        request.method, request.url.path
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Åtkomst nekad för teknikerkonto",
        )
    return user


def require_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.role != models.UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Kräver administratörsrättigheter")
    return current_user

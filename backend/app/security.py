import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_utc, get_db, utcnow
from app.errors import AppError
from app.models import LoginSession, User

hasher = PasswordHasher()
session_cookie = APIKeyCookie(name=get_settings().cookie_name, auto_error=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return hasher.verify(hashed, password)
    except (VerificationError, InvalidHashError):
        return False


def make_session(db: Session, user: User) -> tuple[str, LoginSession]:
    token = secrets.token_urlsafe(32)
    session = LoginSession(
        token_hash=digest(token),
        user_id=user.id,
        csrf_token=secrets.token_hex(32),
        expires_at=utcnow() + timedelta(hours=get_settings().session_hours),
    )
    db.add(session)
    db.flush()
    return (token, session)


def current_user(
    request: Request, db: Session = Depends(get_db), cookie: str | None = Security(session_cookie)
) -> User:
    token = cookie or ""
    session = db.get(LoginSession, digest(token)) if token else None
    if not session or as_utc(session.expires_at) <= utcnow():
        raise AppError(401, "unauthenticated", "Требуется вход")
    user = db.get(User, session.user_id)
    if not user or user.status != "active":
        raise AppError(401, "unauthenticated", "Учетная запись недоступна")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise AppError(403, "csrf_failed", "Недействительный CSRF token")
    request.state.login_session = session
    return user

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_utc, get_db, utcnow
from app.errors import AppError
from app.models import Company, LoginSession, Membership, User

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


def admin_user(user: User = Depends(current_user)) -> User:
    if user.system_role != "admin":
        raise AppError(403, "forbidden", "Требуется роль администратора")
    return user


def company_access(db: Session, user: User, company_id: str) -> Membership:
    if not db.get(Company, company_id):
        raise AppError(404, "not_found", "Компания не найдена")
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.company_id == company_id, Membership.status == "active"
        )
    )
    if not membership:
        raise AppError(403, "forbidden", "Нет доступа к компании")
    return membership


def owned(db: Session, model, object_id: str, user: User):
    obj = db.get(model, object_id)
    if not obj:
        raise AppError(404, "not_found", "Объект не найден")
    if obj.user_id != user.id:
        raise AppError(403, "forbidden", "Нет доступа к объекту")
    company_access(db, user, obj.company_id)
    return obj


def guard_contract(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if request.url.path.startswith("/admin/") and user.system_role != "admin":
        raise AppError(403, "forbidden", "Требуется роль администратора")
    company_id = request.path_params.get("company_id")
    if company_id:
        company_access(db, user, company_id)
    return user

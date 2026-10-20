import secrets

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_utc, get_db, utcnow
from app.errors import AppError
from app.models import LoginSession, User
from app.services.access import company_access
from app.services.sessions import digest

session_cookie = APIKeyCookie(name=get_settings().cookie_name, auto_error=False)


def current_user(
    request: Request,
    db: Session = Depends(get_db, scope="function"),
    cookie: str | None = Security(session_cookie),
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


def guard_contract(
    request: Request, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    if request.url.path.startswith("/admin/") and user.system_role != "admin":
        raise AppError(403, "forbidden", "Требуется роль администратора")
    company_id = request.path_params.get("company_id")
    if company_id:
        company_access(db, user, company_id)
    return user

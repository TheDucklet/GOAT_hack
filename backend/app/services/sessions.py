"""Password verification and server-session creation, independent of HTTP."""

import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import LoginSession, User

hasher = PasswordHasher()


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

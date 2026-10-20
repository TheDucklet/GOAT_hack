from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import LoginSession, Membership, User
from app.schemas import Credentials, LoginCredentials, MeOut, UserOut
from app.security import current_user
from app.services.sessions import hasher, make_session, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserOut, status_code=201)
def register(body: Credentials, db: Session = Depends(get_db, scope="function")):
    email = str(body.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(409, "email_exists", "Email уже зарегистрирован")
    user = User(email=email, password_hash=hasher.hash(body.password))
    db.add(user)
    db.flush()
    return user


@router.post("/auth/login", response_model=MeOut)
def login(
    body: LoginCredentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db, scope="function"),
):
    origin = request.headers.get("origin")
    if origin and origin not in get_settings().cors_origins:
        raise AppError(403, "origin_forbidden", "Недопустимый источник запроса")
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not user or not verify_password(body.password, user.password_hash) or user.status != "active":
        raise AppError(401, "invalid_credentials", "Неверный email или пароль")
    previous = request.cookies.get(get_settings().cookie_name)
    if previous:
        from app.services.sessions import digest

        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(previous)))
    token, session = make_session(db, user)
    response.set_cookie(
        get_settings().cookie_name,
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=get_settings().session_hours * 3600,
        path="/",
    )
    return me_result(db, user, session.csrf_token)


@router.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    db.delete(request.state.login_session)
    response.delete_cookie(get_settings().cookie_name, path="/")


def me_result(db, user, csrf):
    return {
        **UserOut.model_validate(user).model_dump(),
        "csrf_token": csrf,
        "memberships": list(db.scalars(select(Membership).where(Membership.user_id == user.id))),
    }


@router.get("/me", response_model=MeOut)
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")):
    return me_result(db, user, request.state.login_session.csrf_token)

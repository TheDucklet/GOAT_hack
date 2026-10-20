from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import AuditLog, LoginSession, Membership, User
from app.schemas import MembershipOut, MembershipPatch, UserOut, UserPatch
from app.security import admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


def audit(db, admin, action, object_id, details=None):
    db.add(AuditLog(admin_id=admin.id, action=action, object_id=object_id, details=details or {}))


@router.get("/users", response_model=list[UserOut])
def users(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(User).order_by(User.created_at, User.id).offset(offset).limit(limit)))


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: str, body: UserPatch, admin: User = Depends(admin_user), db: Session = Depends(get_db)
):
    obj = db.get(User, user_id)
    if not obj:
        raise AppError(404, "not_found", "Пользователь не найден")
    if obj.id == admin.id and (body.status == "blocked" or body.system_role == "user"):
        raise AppError(409, "self_lockout", "Нельзя отозвать собственный административный доступ")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(obj, key, value)
    if body.status == "blocked" or body.system_role is not None:
        db.execute(delete(LoginSession).where(LoginSession.user_id == obj.id))
    audit(db, admin, "update_user", obj.id, changes)
    return obj


@router.get("/memberships", response_model=list[MembershipOut])
def memberships(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    return list(db.scalars(select(Membership).order_by(Membership.id).offset(offset).limit(limit)))


@router.patch("/memberships/{membership_id}", response_model=MembershipOut)
def patch_membership(
    membership_id: str,
    body: MembershipPatch,
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db),
):
    obj = db.get(Membership, membership_id)
    if not obj:
        raise AppError(404, "not_found", "Членство не найдено")
    obj.status = body.status
    audit(db, admin, "update_membership", obj.id, body.model_dump())
    return obj

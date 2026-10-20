from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import Company, Membership, User
from app.schemas import MembershipIn, MembershipOut, ProfileIn
from app.security import current_user

router = APIRouter(tags=["auth"])


@router.post("/memberships/requests", response_model=MembershipOut, status_code=201)
def request_membership(
    body: MembershipIn, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    company = db.get(Company, body.company_id)
    if not company or company.is_placeholder:
        raise AppError(404, "not_found", "Компания не найдена")
    if db.scalar(
        select(Membership.id).where(Membership.user_id == user.id, Membership.company_id == body.company_id)
    ):
        raise AppError(409, "membership_exists", "Членство или заявка уже существует")
    obj = Membership(user_id=user.id, **body.model_dump())
    db.add(obj)
    db.flush()
    return obj


@router.patch("/memberships/{membership_id}/profile", response_model=MembershipOut)
def update_profile(
    membership_id: str,
    body: ProfileIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    obj = db.get(Membership, membership_id)
    if not obj:
        raise AppError(404, "not_found", "Членство не найдено")
    if obj.user_id != user.id:
        raise AppError(403, "forbidden", "Нельзя изменить чужое членство")
    obj.position_text, obj.interests = (body.position_text, body.interests)
    return obj

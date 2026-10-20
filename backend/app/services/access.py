"""Company/object authorization shared by HTTP, worker and authorized AI tools."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Company, Membership, User


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

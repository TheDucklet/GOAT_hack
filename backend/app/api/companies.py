from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Membership, User
from app.schemas import CompanyOut
from app.security import current_user

router = APIRouter(tags=["companies"])


@router.get("/companies", response_model=list[CompanyOut])
def companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Company)
            .join(Membership)
            .where(Membership.user_id == user.id, Membership.status == "active")
            .order_by(Company.id)
        )
    )

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Membership, User
from app.schemas import CompanyContext, CompanyOut
from app.security import company_access, current_user
from app.services.clients import company_context

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


@router.get("/companies/{company_id}/context", response_model=CompanyContext)
def context(company_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    company_access(db, user, company_id)
    return company_context(db, company_id)

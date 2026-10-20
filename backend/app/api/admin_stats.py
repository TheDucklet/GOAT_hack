from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Feedback, Job, User
from app.schemas import StatsOut
from app.security import admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=StatsOut)
def stats(admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    return {
        "positive_feedback": db.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.rating == 1)
        ),
        "negative_feedback": db.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.rating == -1)
        ),
        "failed_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status == "failed")),
    }

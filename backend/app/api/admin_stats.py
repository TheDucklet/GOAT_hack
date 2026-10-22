from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers.budgeting import default_ledger
from app.ai.providers.settings import get_llm_settings
from app.db import as_utc, get_db, utcnow
from app.models import Feedback, Job, User
from app.schemas import StatsOut
from app.security import admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/runtime-metrics", response_model=dict)
def runtime_metrics(admin: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")):
    oldest = db.scalar(select(func.min(Job.created_at)).where(Job.status == "queued"))
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {
        "jobs": counts,
        "queue_age_seconds": max(0, (utcnow() - as_utc(oldest)).total_seconds()) if oldest else 0,
        "retries": db.scalar(select(func.sum(Job.attempts - 1)).where(Job.attempts > 1)) or 0,
        "max_job_attempts": 3,
        "max_gateway_attempts_per_call": get_llm_settings().llm_max_retries + 1,
        "max_attempts_for_same_call_across_job_retries": 3 * (get_llm_settings().llm_max_retries + 1),
        "budget": default_ledger(get_llm_settings()).status(),
    }


@router.get("/stats", response_model=StatsOut)
def stats(admin: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")):
    return {
        "positive_feedback": db.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.rating == 1)
        ),
        "negative_feedback": db.scalar(
            select(func.count()).select_from(Feedback).where(Feedback.rating == -1)
        ),
        "failed_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status == "failed")),
    }

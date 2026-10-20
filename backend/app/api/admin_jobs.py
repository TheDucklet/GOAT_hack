from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, User
from app.schemas import JobOut
from app.security import admin_user
from app.services.audit import audit
from app.services.queue import enqueue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/jobs", response_model=list[JobOut])
def jobs(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db, scope="function"),
):
    return list(db.scalars(select(Job).order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit)))


@router.post("/jobs/collect-news", response_model=JobOut, status_code=202)
def start_collection(admin: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")):
    job = enqueue(db, "collect_news", {}, admin.id, dedup_key="collect_news")
    audit(db, admin, "collect_news", job.id)
    return job

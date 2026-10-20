from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import Job, User
from app.schemas import JobOut
from app.security import company_access, current_user

router = APIRouter(tags=["analytics"])


@router.get("/jobs/{job_id}", response_model=JobOut)
def job_status(
    job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    job = db.get(Job, job_id)
    if not job:
        raise AppError(404, "not_found", "Задание не найдено")
    if job.user_id != user.id and user.system_role != "admin":
        raise AppError(403, "forbidden", "Задание недоступно")
    if job.company_id:
        company_access(db, user, job.company_id)
    return job

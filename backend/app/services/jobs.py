"""Worker execution/transaction/retry policy; job implementations live in job_handlers.

enqueue/claim_next/scheduler_tick remain public imports for existing integrations.
Producers import services.queue directly and never depend on the worker runtime.
"""

from datetime import timedelta

from sqlalchemy import select

from app.db import session_factory, utcnow
from app.errors import AppError
from app.integrations.ai import AIError
from app.models import Job, User
from app.services.job_handlers import HANDLERS
from app.services.queue import claim_next as claim_next
from app.services.queue import enqueue as enqueue
from app.services.queue import mark_related_failure
from app.services.scheduling import scheduler_tick as scheduler_tick


def execute_job(db, job):
    definition = HANDLERS.get(job.kind)
    if definition is None:
        raise AIError("unknown_job", "Неизвестный тип задания")
    handler, admin_only = definition
    if admin_only and job.user_id:
        actor = db.get(User, job.user_id)
        if not actor or actor.status != "active" or actor.system_role != "admin":
            raise AppError(403, "forbidden", "Административный доступ отозван")
    return handler(db, job)


def run_one() -> bool:
    with session_factory()() as db:
        job_id = claim_next(db)
        if not job_id:
            return False
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        try:
            with db.begin_nested():
                result = execute_job(db, job)
                job.result, job.status, job.error = (result, "done", None)
            job.finished_at, job.dedup_key = (utcnow(), None)
        except Exception as exc:
            db.expire(job)
            code = exc.code if isinstance(exc, (AIError, AppError)) else "processing_failed"
            message = exc.message if isinstance(exc, (AIError, AppError)) else "Ошибка обработки задания"
            job.error = {"code": code, "message": message, "request_id": job.id}
            transient = code in {"source_fetch_failed", "timeout", "rate_limited", "provider_unavailable"}
            if transient and job.attempts < 3:
                job.status, job.available_at = ("queued", utcnow() + timedelta(seconds=5 * 2**job.attempts))
            else:
                job.status, job.finished_at, job.dedup_key = ("failed", utcnow(), None)
                mark_related_failure(db, job, code)
        db.commit()
        return True

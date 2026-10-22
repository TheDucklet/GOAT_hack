"""Worker-only scheduling and abandoned-job recovery."""

from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import as_utc, utcnow
from app.models import Job
from app.services.queue import enqueue, mark_related_failure


def scheduler_tick(db):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(761202602)")):
            return
    now = utcnow()
    last = db.scalar(
        select(Job.created_at).where(Job.kind == "collect_news").order_by(Job.created_at.desc()).limit(1)
    )
    if get_settings().news_collection_enabled and (
        not last or now - as_utc(last) >= timedelta(minutes=get_settings().news_poll_minutes)
    ):
        enqueue(db, "collect_news", {}, dedup_key="collect_news")
    stale = db.scalars(
        select(Job)
        .where(
            Job.status == "running",
            Job.started_at < now - timedelta(seconds=get_settings().job_timeout_seconds),
        )
        .with_for_update(skip_locked=True)
    )
    for job in stale:
        job.status, job.dedup_key, job.finished_at = ("failed", None, now)
        job.error = {
            "code": "worker_lost",
            "message": "Задание прервано; доступен ручной повтор",
            "request_id": job.id,
        }
        mark_related_failure(db, job, "worker_lost")

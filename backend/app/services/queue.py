"""Queue persistence and atomic claiming; importing this never loads handlers."""

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import BankDocument, Event, FeedSnapshot, Job
from app.request_context import received_at


def enqueue(db, kind, payload, user_id=None, company_id=None, dedup_key=None):
    if dedup_key:
        previous = db.scalar(select(Job).where(Job.dedup_key == dedup_key))
        if previous:
            return previous
    job = Job(
        kind=kind,
        payload=payload,
        user_id=user_id,
        company_id=company_id,
        dedup_key=dedup_key,
        received_at=received_at.get() or utcnow(),
    )
    if db.bind.dialect.name == "sqlite":
        # Legacy sqlite3 SAVEPOINT mode may commit a transaction opened by the savepoint.
        # Keep the existing single-process test path under its caller's transaction.
        db.add(job)
        db.flush()
        return job
    try:
        with db.begin_nested():
            db.add(job)
            db.flush()
    except IntegrityError:
        if dedup_key:
            previous = db.scalar(select(Job).where(Job.dedup_key == dedup_key))
            if previous:
                return previous
        raise
    return job


def claim_next(db: Session):
    candidate = db.scalar(
        select(Job.id)
        .where(Job.status == "queued", Job.available_at <= utcnow())
        .order_by(Job.available_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not candidate:
        return None
    claimed = db.scalar(
        update(Job)
        .where(Job.id == candidate, Job.status == "queued")
        .values(status="running", attempts=Job.attempts + 1, started_at=utcnow())
        .returning(Job.id)
    )
    if claimed:
        job = db.get(Job, claimed)
        if job.kind == "ingest_document":
            doc = db.get(BankDocument, job.payload["document_id"])
            if doc:
                doc.status = "running"
    db.commit()
    return claimed


def mark_related_failure(db, job, code):
    if job.kind == "feed_prepare":
        snapshot = db.get(FeedSnapshot, job.payload.get("snapshot_id"))
        if snapshot:
            snapshot.status = "failed"
            snapshot.error = {"code": code}
    elif job.kind == "ingest_document":
        document = db.get(BankDocument, job.payload.get("document_id"))
        if document:
            document.status, document.error = ("failed", code)
    elif job.kind == "summarize":
        event = db.get(Event, job.payload.get("event_id"))
        if event:
            event.processing_status = "failed"

from sqlalchemy import select

from app.errors import AppError
from app.models import Event, Evidence, Job, News


def enqueue(db, kind, payload, user_id=None, company_id=None, dedup_key=None):
    if dedup_key:
        previous = db.scalar(select(Job).where(Job.dedup_key == dedup_key))
        if previous:
            return previous
    job = Job(kind=kind, payload=payload, user_id=user_id, company_id=company_id, dedup_key=dedup_key)
    db.add(job)
    db.flush()
    return job


def event_context(db, event_id):
    event = db.get(Event, event_id)
    if not event or not event.visible:
        raise AppError(404, "not_found", "Событие недоступно")
    news = list(db.scalars(select(News).where(News.event_id == event_id)))
    evidence = list(
        db.scalars(
            select(Evidence).where(Evidence.kind == "news", Evidence.source_id.in_([n.id for n in news]))
        )
    )
    return {
        "id": event.id,
        "title": event.title,
        "summary": event.summary,
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "version": event.version,
        "topics": event.topics,
        "facts": event.facts,
        "publications": [{"id": n.id, "url": n.url, "text": n.text} for n in news],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "source_id": e.source_id,
                "version": e.version,
                "locator": e.locator,
                "excerpt": e.excerpt,
            }
            for e in evidence
        ],
    }

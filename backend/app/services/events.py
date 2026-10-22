"""Authorized callers share one event snapshot for HTTP, jobs and agent tools."""

import hashlib
import json

from sqlalchemy import select

from app.db import as_utc
from app.errors import AppError
from app.models import Event, Evidence, News


def event_version(event):
    content = [
        event.version,
        event.title,
        event.summary,
        event.topics,
        event.facts,
        as_utc(event.published_at).isoformat() if event.published_at else None,
    ]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


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
        "version": event_version(event),
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

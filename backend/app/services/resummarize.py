from sqlalchemy import select

from app.models import Event
from app.services.queue import enqueue


def requeue_summaries(db, version: str, apply: bool) -> int:
    events = list(db.scalars(select(Event).where(Event.processing_status == "done").order_by(Event.id)))
    if apply:
        for event in events:
            enqueue(db, "summarize", {"event_id": event.id}, dedup_key=f"summarize:{event.id}:{version}")
    return len(events)

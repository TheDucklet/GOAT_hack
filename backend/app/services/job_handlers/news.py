"""Collection and summarization handlers."""

from app.integrations.ai import AIError, call_ai
from app.models import Event
from app.schemas import SummaryResult
from app.services.events import event_context
from app.services.evidence import check_refs


def collect_news_job(db, job):
    from app.services.news import collect_news

    result = collect_news(db)
    if not any((s["ok"] for s in result.values())):
        raise AIError("source_fetch_failed", "Все новостные источники недоступны")
    return result


def summarize_job(db, job):
    event = event_context(db, job.payload["event_id"])
    result = SummaryResult.model_validate(call_ai("summarize_event", event=event)).model_dump(mode="json")
    check_refs(db, result, None)
    obj = db.get(Event, event["id"])
    obj.summary, obj.facts, obj.topics = (result["summary"], result["facts"], result["topics"])
    obj.processing_status = "done"
    return {"event_id": obj.id}

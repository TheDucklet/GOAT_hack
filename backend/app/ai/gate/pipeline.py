from datetime import datetime

from app.ai.gate.apply import enforce_publication
from app.ai.impact import build_impact_insight


def news_texts(event: dict) -> dict[str, str]:
    texts = {item["id"]: item["text"] for item in event.get("publications") or []}
    return {
        item["id"]: texts[item["source_id"]]
        for item in event.get("evidence") or []
        if item.get("kind") == "news" and item.get("source_id") in texts
    }


def build_published_insight(
    company_context: dict, user_focus: dict, event: dict, tools, now: datetime | None = None
) -> dict:
    envelope = build_impact_insight(company_context, user_focus, event, tools, now)
    return enforce_publication(envelope, news_texts(event))

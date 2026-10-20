from datetime import datetime

from app.config import get_settings
from app.db import as_utc


def normalized(value):
    return str(value).strip().casefold()


def rank_event(context: dict, focus: dict, event: dict, now: datetime) -> tuple[float, list[dict]]:
    topics = event.get("topics") or {}
    features = context["features"]
    reasons, matches = [], {}
    categories = {
        "industry": ["MAINOKVED_CODE", "MAINOKVED_NAME"],
        "geo": ["REGION", "CITY", "FTS_COUNTRY_NAME"],
    }
    for category, fields in categories.items():
        values = {normalized(t) for t in topics.get(category, [])}
        for field in fields:
            value = features.get(field, {}).get("value")
            if value and normalized(value) in values:
                matches[category] = 1
                reasons.append(
                    {"factor": category, "feature_path": f"features.{field}", "event_topic": str(value)}
                )
                break
    for field in topics.get("product", []):
        if field.startswith("CL_PRODUCT_") or field == "FACTORING_MARK":
            if features.get(field, {}).get("value") in {"1", "1.0", 1, True}:
                matches["product"] = 1
                reasons.append(
                    {"factor": "product", "feature_path": f"features.{field}", "event_topic": field}
                )
                break
    relations = set(context["related_companies"]) | {
        x["company_id"] for side in context["payment_links"].values() for x in side
    }
    overlap = relations & set(topics.get("relation", []))
    if overlap:
        matches["relation"] = 1
        reasons.append(
            {
                "factor": "relation",
                "feature_path": "related_companies/payment_links",
                "event_topic": sorted(overlap)[0],
            }
        )
    focus_overlap = {normalized(t) for t in focus.get("topics", [])} & {
        normalized(t) for values in topics.values() for t in values
    }
    if focus_overlap:
        matches["focus"] = 1
        reasons.append(
            {"factor": "focus", "feature_path": "user_focus.topics", "event_topic": sorted(focus_overlap)[0]}
        )
    published = event.get("published_at")
    if isinstance(published, str):
        published = datetime.fromisoformat(published)
    age = max(0, (now - as_utc(published)).total_seconds() / 86400) if published else None
    freshness = max(0, 1 - age / 7) if age is not None else 0
    score = sum(get_settings().ranking_weights[k] * v for k, v in matches.items()) + freshness
    return round(score, 6), reasons

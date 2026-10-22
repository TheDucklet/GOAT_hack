from dataclasses import dataclass, field
from datetime import date, datetime

from app.ai.schemas import EventPayload
from app.ai.summarization.conflicts import source_conflicts
from app.ai.summarization.vocabulary import PRODUCT_FLAGS, flag_state
from app.data_semantics import confirmed_value


@dataclass(frozen=True)
class Catalog:
    company_id: str
    profile_version: str
    features: dict[str, str]
    company_excerpts: dict[str, str]
    news: dict[str, dict]
    bank_hits: list[dict]
    event_texts: list[str]
    known_features: frozenset[str] = field(default_factory=frozenset)
    flag_states: dict[str, str] = field(default_factory=dict)
    revenue_confirmed: bool = False
    event_day: date | None = None
    conflicts: list[str] = field(default_factory=list)


def event_day_of(payload: EventPayload) -> date | None:
    if not payload.published_at:
        return None
    try:
        return datetime.fromisoformat(payload.published_at).date()
    except ValueError:
        return None


def revenue_is_confirmed(context: dict) -> bool:
    entry = context["features"].get("REVENUE_COMPANY")
    if confirmed_value(entry) is None:
        return False
    return "quality" not in entry or bool(entry.get("unit") and entry.get("period"))


def build_catalog(
    context: dict,
    payload: EventPayload,
    facts: list[dict],
    bank_hits: list[dict],
    company_excerpts: dict[str, str],
) -> Catalog:
    publications = {item.id: item for item in payload.publications}
    news = {}
    for item in payload.evidence:
        if item.kind != "news":
            continue
        publication = publications.get(item.source_id)
        news[item.id] = {
            "id": item.id,
            "kind": "news",
            "source_id": item.source_id,
            "version": item.version,
            "url": item.locator.get("url"),
            "locator": dict(item.locator),
            "excerpt": item.excerpt,
            "text": publication.text if publication else item.excerpt,
        }
    features = {
        name: str(value)
        for name, entry in context["features"].items()
        if (value := confirmed_value(entry)) is not None and str(value).strip()
    }
    return Catalog(
        company_id=context["company_id"],
        profile_version=context["profile_version"],
        features=features,
        company_excerpts=company_excerpts,
        news=news,
        bank_hits=bank_hits,
        event_texts=[payload.title, payload.summary or "", *[claim["text"] for claim in facts]],
        known_features=frozenset(features),
        flag_states={flag: flag_state(context["features"], flag) for flag in PRODUCT_FLAGS},
        revenue_confirmed=revenue_is_confirmed(context),
        event_day=event_day_of(payload),
        conflicts=source_conflicts(facts),
    )

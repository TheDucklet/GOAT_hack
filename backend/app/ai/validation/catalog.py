from dataclasses import dataclass, field

from app.ai.schemas import EventPayload
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
    )

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.ai.insights.context import FEATURE_ORDER
from app.data_semantics import DATA_SEMANTICS_VERSION, normalize_feature

DEFAULT_DIRECTORY = Path("../docs/quality/benchmark")
SYNTHETIC_SHA = "synthetic-benchmark"
ZERO_TOTALS = {"amount": "0.00", "payment_count": 0, "row_count": 0}
STANDARD_UNKNOWNS = ("payment_currency", "payment_period", "revenue_currency", "revenue_reporting_year")
FIRST_SENTENCE_CHARS = 300


@dataclass(frozen=True)
class BenchmarkContext:
    context_id: str
    company_id: str
    role: str
    industry_group: str
    context: dict


def first_sentence(text: str) -> str:
    head = text.split(". ")[0].strip()
    return (head if head.endswith(".") else head + ".")[:FIRST_SENTENCE_CHARS]


def event_payload(item: dict) -> dict:
    publication_id = f"pub-{item['id']}"
    url = item.get("url") or f"https://example.org/synthetic/{item['id']}"
    version = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()[:16]
    return {
        "id": item["id"],
        "title": item["title"],
        "summary": None,
        "published_at": item["published_at"],
        "version": version,
        "topics": None,
        "facts": None,
        "publications": [{"id": publication_id, "url": url, "text": item["text"]}],
        "evidence": [
            {
                "id": f"evidence-{item['id']}",
                "kind": "news",
                "source_id": publication_id,
                "version": version,
                "locator": {"url": url},
                "excerpt": first_sentence(item["text"]),
            }
        ],
    }


def load_events(directory: Path = DEFAULT_DIRECTORY) -> list[dict]:
    return json.loads((directory / "events.json").read_text(encoding="utf-8"))["events"]


def build_context(spec: dict) -> dict:
    rows = spec["rows"]
    variants = [(2, rows)]
    features = {
        field: normalize_feature(field, variants, SYNTHETIC_SHA) for field, value in rows.items() if value
    }
    missing = [field for field in FEATURE_ORDER if field not in features and field != "GROUP_ID"]
    profile_version = hashlib.sha256(
        json.dumps([rows, DATA_SEMANTICS_VERSION], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    group_id = rows.get("GROUP_ID") or None
    return {
        "company_id": spec["company_id"],
        "profile_version": profile_version,
        "group_id": group_id,
        "features": features,
        "unknowns": sorted(
            {*missing, *STANDARD_UNKNOWNS, "REVENUE_COMPANY"}
            if rows.get("REVENUE_COMPANY")
            else {*missing, *STANDARD_UNKNOWNS}
        ),
        "payment_links": {"outgoing": [], "incoming": []},
        "related_companies": [],
        "schema_version": "v2",
        "data_semantics_version": DATA_SEMANTICS_VERSION,
        "identity_quality": "confirmed",
        "client_type": "Client",
        "payment_summary": {
            "outgoing": dict(ZERO_TOTALS),
            "incoming": dict(ZERO_TOTALS),
            "self_payments": dict(ZERO_TOTALS),
            "quarantined": dict(ZERO_TOTALS),
            "unclassified": dict(ZERO_TOTALS),
            "unit": None,
            "period": None,
            "provenance": {"synthetic": True},
        },
        "relationships": [],
        "relationship_coverage": {
            "limit_per_relation": 100,
            "group_truncated": False,
            "person_truncated": False,
        },
        "group_summary": {
            "group_id": group_id,
            "observed_members": 1 if group_id else 0,
            "revenue_covered_members": 0,
            "revenue_sum": None,
            "unit": None,
            "period": None,
            "is_consolidated": False,
            "coverage_scope": "observed_dataset",
        },
    }


def load_positions(directory: Path = DEFAULT_DIRECTORY) -> dict:
    return json.loads((directory / "companies.json").read_text(encoding="utf-8"))["positions"]


def load_contexts(directory: Path = DEFAULT_DIRECTORY) -> list[BenchmarkContext]:
    specs = json.loads((directory / "companies.json").read_text(encoding="utf-8"))["companies"]
    contexts = []
    for spec in specs:
        context = build_context(spec)
        for role in spec["roles"]:
            contexts.append(
                BenchmarkContext(
                    context_id=f"{spec['company_id']}-{role}",
                    company_id=spec["company_id"],
                    role=role,
                    industry_group=spec["industry_group"],
                    context=context,
                )
            )
    return contexts


def pair_id(context_id: str, event_id: str) -> str:
    return f"{context_id}__{event_id}"

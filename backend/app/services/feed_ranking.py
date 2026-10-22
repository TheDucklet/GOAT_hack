"""Deterministic v2 ordering. Impact labels never become an LLM-generated score."""

from copy import deepcopy
from datetime import date

RANKING_VERSION = "feed-rank-2"
# All weights are application policy, not numbers extracted from generated prose.
IMPACT_WEIGHTS = {"high": 30, "medium": 20, "low": 10, "undetermined": 0}
RELEVANCE_WEIGHTS = {"active": 12, "review_required": 3, "undetermined": 0, "expired": -40}


def runtime_result(result: dict, today: date) -> dict:
    value = deepcopy(result)
    if value.get("schema_version") != "v2":
        return value
    end = date.fromisoformat(value["valid_until"]) if value.get("valid_until") else None
    review = date.fromisoformat(value["review_after"]) if value.get("review_after") else None
    start = date.fromisoformat(value["valid_from"]) if value.get("valid_from") else None
    if end and today > end:
        value["relevance_status"] = "expired"
    elif review and today >= review and value["relevance_status"] != "expired":
        value["relevance_status"] = "review_required"
    elif start and today < start and value["relevance_status"] == "active":
        value["relevance_status"] = "review_required"
    # Bank source age uses the referenced PDF dates, never the news timestamp.
    bank = value.get("bank_view_context", {})
    if bank.get("status") == "current" and bank.get("document_dates"):
        from app.ai.rag.temporal import CURRENT_DAYS

        if (today - max(date.fromisoformat(day) for day in bank["document_dates"])).days > CURRENT_DAYS:
            bank["status"] = "historical"
    return value


def score_preview(candidate_score: float, reasons: list[dict], result: dict | None, today: date):
    details = deepcopy(reasons)
    # candidate_score already contains at most one point of source freshness.
    score = candidate_score
    if result and result.get("schema_version") == "v2":
        current = runtime_result(result, today)
        for factor, field, weights, reason in [
            ("impact", "impact_level", IMPACT_WEIGHTS, "impact_reason"),
            ("relevance", "relevance_status", RELEVANCE_WEIGHTS, "relevance_reason"),
        ]:
            label = current[field]
            contribution = weights[label]
            # A named level without references never contributes to rank.
            refs = (current.get(reason) or {}).get("evidence_refs", [])
            if not refs:
                contribution = 0
            score += contribution
            details.append(
                dict(
                    factor=factor,
                    value=label,
                    contribution=contribution,
                    evidence_refs=refs,
                    policy=RANKING_VERSION,
                )
            )
    return round(score, 6), details

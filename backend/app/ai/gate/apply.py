import copy

from pydantic import ValidationError

from app.ai.gate.prompts import GATE_PROMPT_VERSION
from app.ai.gate.verify import verify_checked
from app.ai.impact.assemble import next_actions
from app.ai.schemas import InsightEnvelopeV2
from app.publication_policy import (
    CRITICAL_SECTIONS,
    INSIGHT_SECTIONS,
    PUBLICATION_POLICY_VERSION,
    content_digest,
    insight_claims,
)

MAX_UNKNOWNS = 12
PUBLISHABLE = frozenset({"all_supported", "repaired_by_removal"})
BANK_REMOVED = (
    "Позиция банка не показана: утверждения не подтверждены источниками при проверке перед публикацией"
)
FACTS_REMOVED = "В событии нет проверенных фактов: утверждения не подтверждены источниками"
IMPACT_REMOVED = (
    "Сила влияния не определена: механизм или его обоснование не подтверждены источниками при проверке"
)
RELEVANCE_REMOVED = "Срок актуальности вывода не подтверждён источниками при проверке"


def source_map(envelope: dict, news_texts: dict[str, str]) -> dict[str, dict]:
    sources = {}
    for item in envelope["evidence"]:
        text = news_texts.get(item["id"]) if item["kind"] == "news" else None
        sources[item["id"]] = {
            "kind": item["kind"],
            "text": text or item["excerpt"],
            "locator": item.get("locator") or {},
        }
    return sources


def refresh_bank_context(result: dict, evidence: list[dict]) -> None:
    context = result["bank_view_context"]
    if not result["bank_view"]:
        return
    catalogue = {item["id"]: item for item in evidence}
    dates = sorted(
        {
            catalogue[ref]["locator"]["document_date"]
            for claim in result["bank_view"]
            for ref in claim["evidence_refs"]
            if catalogue[ref]["locator"].get("document_date")
        }
    )
    if dates and dates != list(context["document_dates"]):
        status = "historical" if context["status"] == "current" else context["status"]
        result["bank_view_context"] = {"status": status, "document_dates": dates}


def drop(
    result: dict, failed: set[str], evidence: list[dict], restore: bool = False
) -> tuple[dict, list[dict]]:
    result = copy.deepcopy(result)
    changes: list[dict] = []
    unknowns = list(result["unknowns"])
    for section in INSIGHT_SECTIONS:
        items = result.get(section)
        if items is None:
            continue
        kept = [claim for claim in items if claim["claim_id"] not in failed]
        result[section] = kept
    if result["bank_view"] is not None and not result["bank_view"]:
        result["bank_view"] = None
        result["bank_view_context"] = {"status": "missing", "document_dates": []}
        unknowns.append(BANK_REMOVED)
        changes.append({"field": "bank_view", "action": "removed", "because": "bank claims not supported"})
    refresh_bank_context(result, evidence)
    if not result["facts"]:
        unknowns.append(FACTS_REMOVED)
    for field in ("personalized_summary", "impact_reason", "relevance_reason"):
        if result.get(field) and result[field]["claim_id"] in failed:
            result[field] = None
    if restore and result["facts"]:
        kinds = {item["id"]: item["kind"] for item in evidence}
        if not result["mechanism"]:
            # Only claims supported in the first pass survived the pruning.
            # Copy a grounded alternative; never invent a fallback paragraph.
            alternative = next(
                (
                    claim
                    for claim in result["ai_interpretation"]
                    if {"news", "company"}
                    <= {kinds.get(ref) for ref in claim["evidence_refs"]}
                ),
                None,
            )
            if alternative:
                result["mechanism"] = [{**alternative, "claim_id": "mechanism-restored"}]
                result["impact_level"] = "undetermined"
                result["impact_reason"] = None
                changes.append(
                    {"field": "mechanism", "action": "restored_from_verified_interpretation",
                     "source_claim_id": alternative["claim_id"]}
                )
        if result["mechanism"]:
            first = result["mechanism"][0]
            result["personalized_summary"] = {**first, "claim_id": "summary-restored"}
            changes.append({"field": "personalized_summary", "action": "copied_from_mechanism"})
    broken = (
        not result["mechanism"] or result["personalized_summary"] is None or result["impact_reason"] is None
    )
    if result["impact_level"] != "undetermined" and broken:
        changes.append(
            {
                "field": "impact_level",
                "action": f"{result['impact_level']} -> undetermined",
                "because": "no supported basis",
            }
        )
        result["impact_level"] = "undetermined"
        unknowns.append(IMPACT_REMOVED)
    if result["impact_level"] == "undetermined":
        if result["relevance_reason"] is not None or result["relevance_status"] != "undetermined":
            changes.append({"field": "relevance", "action": "cleared", "because": "impact undetermined"})
        result["relevance_reason"] = None
        result["relevance_status"] = "undetermined"
        result["valid_from"] = result["valid_until"] = result["review_after"] = None
        result["next_actions"] = next_actions(False)
        if not result["mechanism"]:
            result["personalized_summary"] = None
            result["impact_reason"] = None
            result["assumptions"] = []
    elif result["relevance_reason"] is None and result["relevance_status"] != "undetermined":
        result["relevance_status"] = "undetermined"
        result["valid_from"] = result["valid_until"] = result["review_after"] = None
        unknowns.append(RELEVANCE_REMOVED)
        changes.append(
            {"field": "relevance", "action": "cleared", "because": "relevance_reason not supported"}
        )
    claims = insight_claims(result)
    result["evidence_refs"] = list(dict.fromkeys(ref for claim in claims for ref in claim["evidence_refs"]))
    result["unknowns"] = list(dict.fromkeys(item for item in unknowns if item.strip()))[:MAX_UNKNOWNS]
    return result, changes


def rebuilt(envelope: dict, result: dict) -> dict:
    refs = set(result["evidence_refs"])
    value = {
        "result": result,
        "evidence": [item for item in envelope["evidence"] if item["id"] in refs],
        "trace": envelope["trace"],
    }
    return InsightEnvelopeV2.model_validate(value).model_dump(mode="json")


def entry(claim: dict, verdict: dict, versions: dict[str, str]) -> dict:
    return {
        "claim_id": claim["claim_id"],
        "section": claim["section"],
        "statement_type": claim["statement_type"],
        "evidence": [
            {"id": ref, "version": versions[ref]} for ref in claim["evidence_refs"] if ref in versions
        ],
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
    }


def report_of(
    envelope: dict,
    verdicts: dict[str, dict],
    removed: list[dict],
    changes: list[dict],
    attempts: int,
    stop_reason: str,
    usage: list[dict],
) -> dict:
    result = envelope["result"]
    versions = {item["id"]: item["version"] for item in envelope["evidence"]}
    claims = insight_claims(result)
    entries = [entry(claim, verdicts[claim["claim_id"]], versions) for claim in claims]
    supported = sum(1 for item in entries if item["verdict"] == "supported")
    unresolved = [item["claim_id"] for item in entries if item["verdict"] != "supported"]
    decision = "allow" if not unresolved and result["facts"] and stop_reason in PUBLISHABLE else "block"
    if decision == "block" and stop_reason in PUBLISHABLE:
        stop_reason = "no_verified_facts"
    return {
        "policy_version": PUBLICATION_POLICY_VERSION,
        "verifier_prompt_version": GATE_PROMPT_VERSION,
        "decision": decision,
        "decided_by": "code",
        "content_digest": content_digest(result),
        "required": len(claims),
        "checked": len(entries),
        "supported": supported,
        "claims": entries,
        "removed": removed,
        "dependent_changes": changes,
        "unresolved_critical": [
            item["claim_id"]
            for item in entries
            if item["verdict"] != "supported" and item["section"] in CRITICAL_SECTIONS
        ],
        "unresolved": unresolved,
        "repair_attempts": attempts,
        "stop_reason": stop_reason,
        "usage": usage,
        "cost_rub": round(sum(item["cost_rub"] for item in usage), 6),
    }


def with_report(envelope: dict, report: dict) -> dict:
    envelope["trace"] = {**envelope["trace"], "publication": report}
    return envelope


def enforce_publication(envelope: dict, news_texts: dict[str, str]) -> dict:
    envelope = copy.deepcopy(envelope)
    sources = source_map(envelope, news_texts)
    claims = insight_claims(envelope["result"])
    verdicts, usage = verify_checked(claims, sources)
    failed = {claim_id for claim_id, item in verdicts.items() if item["verdict"] != "supported"}
    removed: list[dict] = []
    changes: list[dict] = []
    attempts, stop_reason = 0, "all_supported"
    if failed or (not envelope["result"]["mechanism"] and envelope["result"]["ai_interpretation"]):
        attempts = 1
        removed = [
            {
                "claim_id": claim["claim_id"],
                "section": claim["section"],
                "verdict": verdicts[claim["claim_id"]]["verdict"],
                "reason": verdicts[claim["claim_id"]]["reason"],
            }
            for claim in claims
            if claim["claim_id"] in failed
        ]
        repaired, changes = drop(envelope["result"], failed, envelope["evidence"], restore=True)
        try:
            candidate = rebuilt(envelope, repaired)
        except (ValidationError, ValueError):
            report = report_of(envelope, verdicts, removed, changes, attempts, "repair_invalid", usage)
            report["decision"] = "block"
            return with_report(envelope, report)
        rejected = [
            item["text"][:200]
            for item in claims
            if item["claim_id"] in failed and item["section"] in CRITICAL_SECTIONS
        ]
        remaining = insight_claims(candidate["result"])
        sources = source_map(candidate, news_texts)
        verdicts, again = verify_checked(remaining, sources, rejected)
        usage = usage + again
        envelope = candidate
        stop_reason = "repaired_by_removal"
        failed_again = {claim_id for claim_id, item in verdicts.items() if item["verdict"] != "supported"}
        if failed_again:
            removed += [
                {
                    "claim_id": claim["claim_id"],
                    "section": claim["section"],
                    "verdict": verdicts[claim["claim_id"]]["verdict"],
                    "reason": verdicts[claim["claim_id"]]["reason"],
                }
                for claim in remaining
                if claim["claim_id"] in failed_again
            ]
            pruned, more = drop(candidate["result"], failed_again, candidate["evidence"])
            changes = changes + more
            try:
                envelope = rebuilt(candidate, pruned)
            except (ValidationError, ValueError):
                report = report_of(candidate, verdicts, removed, changes, attempts, "repair_invalid", usage)
                report["decision"] = "block"
                return with_report(candidate, report)
    return with_report(
        envelope, report_of(envelope, verdicts, removed, changes, attempts, stop_reason, usage)
    )

import copy

from app.ai.gate.apply import source_map, with_report
from app.ai.gate.prompts import GATE_PROMPT_VERSION
from app.ai.gate.verify import verify_checked
from app.publication_policy import (
    PUBLICATION_POLICY_VERSION,
    SERVICE_ANSWER_KIND,
    chat_claims,
    content_digest,
)

SERVICE_ANSWER = "Не удалось подтвердить ответ источниками. Уточните вопрос или добавьте данные о компании."


def chat_report(
    envelope: dict, verdicts: dict[str, dict], usage: list[dict], decision: str, stop: str
) -> dict:
    result = envelope["result"]
    versions = {item["id"]: item["version"] for item in envelope["evidence"]}
    claims = chat_claims(result) if decision == "allow" else []
    entries = [
        {
            "claim_id": claim["claim_id"],
            "section": claim["section"],
            "statement_type": claim["statement_type"],
            "evidence": [
                {"id": ref, "version": versions[ref]} for ref in claim["evidence_refs"] if ref in versions
            ],
            "verdict": verdicts[claim["claim_id"]]["verdict"],
            "reason": verdicts[claim["claim_id"]]["reason"],
        }
        for claim in claims
    ]
    supported = sum(1 for item in entries if item["verdict"] == "supported")
    return {
        "policy_version": PUBLICATION_POLICY_VERSION,
        "verifier_prompt_version": GATE_PROMPT_VERSION,
        "decision": decision,
        "decided_by": "code",
        "content_digest": content_digest(result),
        "required": len(entries),
        "checked": len(entries),
        "supported": supported,
        "claims": entries,
        "removed": [],
        "dependent_changes": [],
        "unresolved_critical": [],
        "unresolved": [item["claim_id"] for item in entries if item["verdict"] != "supported"],
        "repair_attempts": 0,
        "stop_reason": stop,
        "usage": usage,
        "cost_rub": round(sum(item["cost_rub"] for item in usage), 6),
    }


def service_envelope(envelope: dict, usage: list[dict], stop: str) -> dict:
    envelope["result"] = {**envelope["result"], "answer": SERVICE_ANSWER, "evidence_refs": []}
    envelope["evidence"] = []
    return with_report(envelope, chat_report(envelope, {}, usage, SERVICE_ANSWER_KIND, stop))


def enforce_chat(envelope: dict, news_texts: dict[str, str]) -> dict:
    envelope = copy.deepcopy(envelope)
    if not envelope["result"].get("evidence_refs"):
        return with_report(envelope, chat_report(envelope, {}, [], SERVICE_ANSWER_KIND, "no_evidence"))
    sources = source_map(envelope, news_texts)
    claims = chat_claims(envelope["result"])
    verdicts, usage = verify_checked(claims, sources)
    kept = [claim for claim in claims if verdicts[claim["claim_id"]]["verdict"] == "supported"]
    if len(kept) == len(claims):
        return with_report(envelope, chat_report(envelope, verdicts, usage, "allow", "all_supported"))
    if not kept:
        return service_envelope(envelope, usage, "no_supported_sentences")
    envelope["result"] = {**envelope["result"], "answer": " ".join(claim["text"] for claim in kept)}
    again = chat_claims(envelope["result"])
    verdicts, more = verify_checked(
        again, sources, [item["text"][:200] for item in claims if item not in kept]
    )
    usage = usage + more
    if all(item["verdict"] == "supported" for item in verdicts.values()):
        return with_report(envelope, chat_report(envelope, verdicts, usage, "allow", "all_supported"))
    return service_envelope(envelope, usage, "repair_failed")

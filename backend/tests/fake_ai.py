"""Deterministic test implementations; never imported by a production configuration."""

from uuid import uuid4

from app.publication_policy import (
    PUBLICATION_POLICY_VERSION,
    chat_claims,
    content_digest,
    insight_claims,
)


def allowed(envelope, kind="insight"):
    from app.schemas import ChatResult, parse_insight_result

    raw = envelope["result"]
    model = parse_insight_result(raw) if kind == "insight" else ChatResult.model_validate(raw)
    result = model.model_dump(mode="json")
    claims = insight_claims(result) if kind == "insight" else chat_claims(result)
    versions = {item["id"]: item["version"] for item in envelope["evidence"]}
    entries = [
        {
            "claim_id": claim["claim_id"],
            "section": claim["section"],
            "statement_type": claim.get("statement_type", "fact"),
            "evidence": [
                {"id": ref, "version": versions[ref]} for ref in claim["evidence_refs"] if ref in versions
            ],
            "verdict": "supported",
            "reason": "",
        }
        for claim in claims
    ]
    report = {
        "policy_version": PUBLICATION_POLICY_VERSION,
        "verifier_prompt_version": "test-gate",
        "decision": "allow",
        "decided_by": "code",
        "content_digest": content_digest(result),
        "required": len(entries),
        "checked": len(entries),
        "supported": len(entries),
        "claims": entries,
        "removed": [],
        "dependent_changes": [],
        "unresolved_critical": [],
        "unresolved": [],
        "repair_attempts": 0,
        "stop_reason": "all_supported",
    }
    envelope["trace"] = {**envelope["trace"], "publication": report}
    return envelope


def derive_user_focus(position_text, interests):
    return {"topics": interests, "priorities": [], "unknowns": [], "version": "test-v1"}


def summarize_event(event):
    evidence_id = event["evidence"][0]["id"]
    return {
        "summary": event["title"],
        "facts": [{"claim_id": "fact-1", "text": event["title"], "evidence_refs": [evidence_id]}],
        "entities": [],
        "topics": {"product": ["CL_PRODUCT_LOA_MARK"]},
    }


def build_insight(company_context, user_focus, event, tools):
    assert tools.get_company_context()["company_id"] == company_context["company_id"]
    ref = event["evidence"][0]["id"]
    claim = {"claim_id": "fact-1", "text": "Test source fact", "evidence_refs": [ref]}
    return allowed(
        {
            "result": {
                "facts": [claim],
                "bank_view": None,
                "ai_interpretation": [{**claim, "claim_id": "interpretation-1"}],
                "risks": [],
                "opportunities": [],
                "actions": [],
                "unknowns": ["loan_amount"],
                "evidence_refs": [ref],
                "trace_id": str(uuid4()),
            },
            "evidence": [event["evidence"][0]],
            "trace": {"plan": ["read_event", "check_sources"]},
        }
    )


def answer_chat(company_context, user_focus, event, history, tools):
    assert tools.get_event()["id"] == event["id"]
    return allowed(
        {
            "result": {
                "answer": "Missing loan_amount; question: " + history[-1]["text"],
                "evidence_refs": [event["evidence"][0]["id"]],
                "unknowns": ["loan_amount"],
                "trace_id": str(uuid4()),
                "usage": {},
            },
            "evidence": [event["evidence"][0]],
            "trace": {"steps": []},
        },
        "chat",
    )


def ingest_bank_document(document, path):
    return {
        "document_date": None,
        "chunks": [
            {"page": page, "text": f"Synthetic OCR page {page}"}
            for page in range(1, document["page_count"] + 1)
        ],
    }

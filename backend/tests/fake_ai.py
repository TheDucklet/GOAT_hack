"""Deterministic test implementations; never imported by a production configuration."""

from uuid import uuid4


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
    return {
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
        "evidence": [],
        "trace": {"plan": ["read_event", "check_sources"]},
    }


def answer_chat(company_context, user_focus, event, history, tools):
    assert tools.get_event()["id"] == event["id"]
    return {
        "result": {
            "answer": "Missing loan_amount; question: " + history[-1]["text"],
            "evidence_refs": [event["evidence"][0]["id"]],
            "unknowns": ["loan_amount"],
            "trace_id": str(uuid4()),
            "usage": {},
        },
        "evidence": [],
        "trace": {"steps": []},
    }


def ingest_bank_document(document, path):
    return {
        "document_date": None,
        "chunks": [
            {"page": page, "text": f"Synthetic OCR page {page}"}
            for page in range(1, document["page_count"] + 1)
        ],
    }

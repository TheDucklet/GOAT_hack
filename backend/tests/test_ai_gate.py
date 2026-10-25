import copy
import json
from pathlib import Path

import pytest

from app.ai.gate import apply as gate_apply
from app.ai.gate import verify as gate_verify
from app.ai.gate.apply import enforce_publication
from app.ai.gate.chat import SERVICE_ANSWER, enforce_chat
from app.ai.providers import LLMError
from app.publication_policy import content_digest, report_problems
from tests.support_gate import Verifier

FIXTURES = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/contracts/insight-v2-examples.json").read_text(
        encoding="utf-8"
    )
)
FULL = next(item["envelope"] for item in FIXTURES if item["name"] == "historical_bank_position")
NEWS = {item["id"]: "Полный текст публикации." for item in FULL["evidence"] if item["kind"] == "news"}


def claim_ids(envelope):
    result = envelope["result"]
    ids = {"fact": [item["claim_id"] for item in result["facts"]]}
    ids["bank"] = [item["claim_id"] for item in result["bank_view"] or []]
    ids["mechanism"] = [item["claim_id"] for item in result["mechanism"]]
    ids["summary"] = result["personalized_summary"]["claim_id"]
    ids["reason"] = result["impact_reason"]["claim_id"]
    return ids


def run(monkeypatch, verifier, envelope=None):
    monkeypatch.setattr(gate_verify, "call_llm", verifier)
    return enforce_publication(copy.deepcopy(envelope or FULL), NEWS)


def check(envelope, kind="insight"):
    return report_problems(envelope["trace"]["publication"], envelope["result"], envelope["evidence"], kind)


def test_everything_supported_is_allowed_with_full_coverage(monkeypatch):
    envelope = run(monkeypatch, Verifier())
    report = envelope["trace"]["publication"]
    assert report["decision"] == "allow" and report["decided_by"] == "code"
    assert report["required"] == report["checked"] == report["supported"] == len(report["claims"]) > 0
    assert report["content_digest"] == content_digest(envelope["result"])
    assert check(envelope) == []
    assert envelope["result"]["bank_view"] and envelope["result"]["impact_level"] == "high"


def test_rejected_bank_claim_is_removed_and_the_rest_is_rechecked(monkeypatch):
    bank = claim_ids(FULL)["bank"][0]
    verifier = Verifier({bank: "unsupported"})
    envelope = run(monkeypatch, verifier)
    report = envelope["trace"]["publication"]
    assert report["decision"] == "allow" and report["repair_attempts"] == 1
    assert envelope["result"]["bank_view"] is None
    assert envelope["result"]["bank_view_context"]["status"] == "missing"
    assert any(item["claim_id"] == bank and item["section"] == "bank_view" for item in report["removed"])
    assert any("Позиция банка не показана" in item for item in envelope["result"]["unknowns"])
    assert len(verifier.payloads) == 2 and all(bank != item["id"] for item in verifier.payloads[1]["claims"])
    assert check(envelope) == []


def test_rejected_fact_is_passed_as_a_rejected_premise_and_blocks_dependents(monkeypatch):
    ids = claim_ids(FULL)
    verifier = Verifier({ids["fact"][0]: "contradicted", (1, ids["mechanism"][0]): "unsupported"})
    envelope = run(monkeypatch, verifier)
    report = envelope["trace"]["publication"]
    assert verifier.payloads[1]["rejected_premises"]
    assert report["decision"] == "block" and report["stop_reason"] in {"repair_failed", "no_verified_facts"}
    assert check(envelope)


def test_rejected_mechanism_downgrades_the_impact_instead_of_keeping_it(monkeypatch):
    mechanism = claim_ids(FULL)["mechanism"][0]
    envelope = run(monkeypatch, Verifier({mechanism: "unsupported"}))
    result, report = envelope["result"], envelope["trace"]["publication"]
    assert report["decision"] == "allow"
    assert result["impact_level"] == "undetermined" and result["mechanism"] == []
    assert result["personalized_summary"] is None and result["impact_reason"] is None
    assert result["relevance_status"] == "undetermined" and result["unknowns"]
    assert {"field": "impact_level", "action": "high -> undetermined", "because": "no supported basis"} in (
        report["dependent_changes"]
    )
    assert check(envelope) == []


def test_missing_verdict_is_never_supported(monkeypatch):
    bank = claim_ids(FULL)["bank"][0]
    envelope = run(monkeypatch, Verifier(omit={bank}))
    report = envelope["trace"]["publication"]
    removed = next(item for item in report["removed"] if item["claim_id"] == bank)
    assert removed["verdict"] == "unverified"
    assert report["decision"] == "allow" and envelope["result"]["bank_view"] is None


def test_second_pass_failure_blocks_without_another_attempt(monkeypatch):
    ids = claim_ids(FULL)
    verifier = Verifier({ids["bank"][0]: "unsupported", (1, ids["summary"]): "unsupported"})
    envelope = run(monkeypatch, verifier)
    report = envelope["trace"]["publication"]
    assert report["decision"] == "block" and report["stop_reason"] == "repair_failed"
    assert len(verifier.payloads) == 2 and report["repair_attempts"] == 1
    assert check(envelope)


def test_verifier_failure_is_an_error_not_a_ready_card(monkeypatch):
    with pytest.raises(LLMError):
        run(monkeypatch, Verifier(error=LLMError("provider_unavailable", "req")))


def test_report_cannot_vouch_for_changed_or_extended_content(monkeypatch):
    envelope = run(monkeypatch, Verifier())
    tampered = copy.deepcopy(envelope)
    tampered["result"]["unknowns"] = [*tampered["result"]["unknowns"], "добавлено позже"]
    assert any("другому содержимому" in item for item in check(tampered))
    extended = copy.deepcopy(envelope)
    extended["result"]["risks"] = [
        {**extended["result"]["facts"][0], "claim_id": "late-risk", "statement_type": "hypothesis"}
    ]
    extended["trace"]["publication"]["content_digest"] = content_digest(extended["result"])
    assert any("не все обязательные" in item for item in check(extended))
    stale = copy.deepcopy(envelope)
    stale["trace"]["publication"]["policy_version"] = "publication-0"
    assert any("версия политики" in item for item in check(stale))
    model_decided = copy.deepcopy(envelope)
    model_decided["trace"]["publication"]["decided_by"] = "model"
    assert any("не кодом" in item for item in check(model_decided))


def test_every_critical_section_is_a_mandatory_claim(monkeypatch):
    envelope = run(monkeypatch, Verifier())
    sections = {item["section"] for item in envelope["trace"]["publication"]["claims"]}
    assert {"facts", "bank_view", "mechanism", "personalized_summary", "impact_reason"} <= sections


CHAT = {
    "result": {
        "answer": "Первое предложение подтверждено. Второе предложение выдумано.",
        "evidence_refs": [FULL["evidence"][0]["id"]],
        "unknowns": [],
        "trace_id": "t1",
        "usage": {},
    },
    "evidence": [FULL["evidence"][0]],
    "trace": {},
}


def run_chat(monkeypatch, verifier, envelope=None):
    monkeypatch.setattr(gate_verify, "call_llm", verifier)
    return enforce_chat(copy.deepcopy(envelope or CHAT), NEWS)


def test_chat_keeps_only_supported_sentences_after_a_recheck(monkeypatch):
    envelope = run_chat(monkeypatch, Verifier({"answer-2": "unsupported"}))
    assert envelope["result"]["answer"] == "Первое предложение подтверждено."
    assert envelope["trace"]["publication"]["decision"] == "allow"
    assert (
        report_problems(envelope["trace"]["publication"], envelope["result"], envelope["evidence"], "chat")
        == []
    )


def test_chat_without_any_supported_sentence_becomes_a_service_message(monkeypatch):
    envelope = run_chat(monkeypatch, Verifier({"answer-1": "unsupported", "answer-2": "unsupported"}))
    assert envelope["result"]["answer"] == SERVICE_ANSWER and envelope["result"]["evidence_refs"] == []
    assert envelope["trace"]["publication"]["decision"] == "service_message"
    assert envelope["trace"]["publication"]["required"] == 0


def test_chat_refusal_without_evidence_is_a_service_message_without_a_model_call(monkeypatch):
    verifier = Verifier()
    envelope = {**copy.deepcopy(CHAT), "result": {**CHAT["result"], "evidence_refs": []}}
    result = run_chat(monkeypatch, verifier, envelope)
    assert result["trace"]["publication"]["decision"] == "service_message" and not verifier.payloads


def test_apply_module_does_not_trust_model_text_for_the_decision():
    assert "decision" not in gate_verify.RawVerdict.model_fields
    assert gate_apply.PUBLICATION_POLICY_VERSION

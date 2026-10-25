import json
from pathlib import Path

import pytest

from app.ai.benchmark.data import load_contexts
from app.ai.gate.guards import apply_condition_guard
from app.ai.insights.context import company_facts, mechanism_bases
from app.ai.providers.testing import json_completion
from app.ai.schemas import EventPayload
from app.ai.summarization.conditions import condition_context
from tests.support_gate import Verifier
from tests.test_ai_impact import ImpactRouter, credit_response, make, pick, statement
from tests.test_ai_summaries import event, raw_answer, run_summary

BENCHMARK = Path(__file__).resolve().parents[2] / "docs/quality/benchmark"


def test_missing_credit_keeps_industry_and_confirmed_deposit_as_reasoning_bases():
    ctx = next(c.context for c in load_contexts(BENCHMARK) if c.company_id == "B02")
    facts = company_facts(ctx)
    aliases = {f"C{i}": fact.evidence_id for i, fact in enumerate(facts, 1)}
    bases = mechanism_bases(facts, aliases)
    references = {item["id"] for item in bases}
    for fact in facts:
        alias = next(k for k, value in aliases.items() if value == fact.evidence_id)
        if fact.feature == "CL_PRODUCT_LOA_MARK":
            assert alias not in references
        if fact.feature in {"MAINOKVED_NAME", "CL_PRODUCT_DEP_MARK"}:
            assert alias in references
    assert references <= set(aliases)


@pytest.mark.parametrize("threshold", [50, 70, 85])
def test_short_summary_cannot_silently_lose_a_source_eligibility_threshold(monkeypatch, threshold):
    condition = f"Условием остаётся доля профильных доходов не менее {threshold}%."
    text = "Для отрасли продлена льгота. " + condition
    raw = raw_answer(summary="Для отрасли продлена льгота.", facts=[])
    result, _ = run_summary(monkeypatch, json_completion(raw), payload=event(text))
    assert any(item["text"] == condition and item["evidence_refs"] == ["ev-1"] for item in result["facts"])


def test_retained_condition_still_requires_a_semantic_verdict(monkeypatch):
    condition = "Условием остаётся доля профильных доходов не менее 70%."
    rejected = Verifier({"check-fact-1": "unsupported"})
    result, _ = run_summary(
        monkeypatch,
        json_completion(raw_answer(summary="Льгота продлена.", facts=[])),
        json_completion(raw_answer(summary="Льгота продлена.", facts=[])),
        payload=event("Льгота продлена. " + condition),
        verifier=rejected,
    )
    assert result["facts"] == []
    assert len(rejected.payloads) == 2


def test_legacy_summary_conditions_are_bound_only_to_the_cited_publication():
    payload = event("Условием остаётся доля профильных доходов не менее 70%.")
    assert condition_context(EventPayload.model_validate(payload), {}) == []
    conditions = condition_context(EventPayload.model_validate(payload), {"N1": "ev-1"})
    assert conditions == [{"evidence_id": "N1", "text": payload["publications"][0]["text"]}]


@pytest.mark.parametrize("threshold", [50, 70, 85])
def test_gate_rejects_an_omitted_condition_even_when_the_model_says_supported(threshold):
    sources = {
        "news": {"kind": "news", "text": f"Условием получения субсидии является доля доходов не менее {threshold}%."},
        "other": {"kind": "news", "text": "Ставка сохранена."},
    }
    claims = [
        {"claim_id": "partial", "section": "mechanism", "text": "Если компания аккредитована, то она может получить субсидию.", "evidence_refs": ["news"]},
        {"claim_id": "complete", "section": "mechanism", "text": f"Если компания аккредитована и доля доходов не менее {threshold}%, то она может получить субсидию.", "evidence_refs": ["news"]},
        {"claim_id": "unrelated", "section": "mechanism", "text": "Если появится новый договор, условия могут зависеть от ставки.", "evidence_refs": ["other"]},
    ]
    verdicts = {claim["claim_id"]: {"verdict": "supported", "reason": "model"} for claim in claims}
    checked = apply_condition_guard(claims, sources, verdicts)
    assert checked["partial"]["verdict"] == "unsupported"
    assert checked["complete"]["verdict"] == checked["unrelated"]["verdict"] == "supported"


def test_a_noncredit_profile_can_keep_a_deposit_mechanism_with_unknown_impact(monkeypatch):
    ctx = next(c.context for c in load_contexts(BENCHMARK) if c.company_id == "B02")

    def answer(payload):
        deposit = pick(payload, "депозит")
        value = credit_response(payload, level="undetermined")
        value.update(
            summary=None,
            mechanism=[statement("Если компания планирует новое размещение средств, то сохранение ставки может влиять на условия депозита.", "N1", deposit)],
            impact_reason=None,
            assumptions=[],
        )
        return value

    router = ImpactRouter(impact=answer)
    result = make(monkeypatch, router, ctx)["result"]
    assert result["impact_level"] == "undetermined" and result["mechanism"] and result["personalized_summary"]
    payload = json.loads(router.impact_requests[0].user)
    assert payload["mechanism_bases"]

import pytest

from app.ai.providers.testing import completion, json_completion
from app.ai.providers.transport import TransportFailure
from tests.test_ai_agent import Router, Search, run
from tests.test_ai_insights import GOOD, hit

UNSUPPORTED = {
    **GOOD,
    "bank_view": [{"text": "Альфа-Банк рекомендует немедленно закрыть компанию.", "evidence_ids": ["B1"]}],
}


class VerifierRouter(Router):
    def __init__(self, behaviour, **kwargs):
        super().__init__(insight=[UNSUPPORTED], **kwargs)
        self.behaviour = behaviour

    def send(self, request):
        if "проверяешь, подтверждают ли" in request.system:
            self.requests.append(request)
            self.calls["verify"] += 1
            outcome = self.behaviour(request)
            if isinstance(outcome, Exception):
                raise outcome
            return completion(outcome) if isinstance(outcome, str) else json_completion(outcome)
        return super().send(request)


def run_with(monkeypatch, behaviour):
    router = VerifierRouter(behaviour)
    envelope, _ = run(monkeypatch, router, Search(default=[hit()]), max_extra_searches=1)
    return envelope, router


def assert_fails_closed(envelope):
    result, trace = envelope["result"], envelope["trace"]
    assert result["bank_view"] is None
    assert all(
        "закрыть компанию" not in claim["text"] for claim in result["ai_interpretation"] + result["risks"]
    )
    rejected = trace["checks"][0]["rejected_bank_claims"]
    assert rejected and rejected[0]["verdict"] == "unverified"
    assert any("смысловая проверка утверждений не выполнена" in item for item in result["unknowns"])


@pytest.mark.parametrize("kind", ["timeout", "provider_unavailable"])
def test_unavailable_verifier_does_not_keep_the_bank_claim(monkeypatch, kind):
    envelope, router = run_with(monkeypatch, lambda request: TransportFailure(kind))
    assert_fails_closed(envelope)
    assert router.calls["verify"] >= 1


def test_rate_limited_verifier_does_not_keep_the_bank_claim(monkeypatch):
    from app.ai.providers.testing import http_error

    class Limited(VerifierRouter):
        def send(self, request):
            if "проверяешь, подтверждают ли" in request.system:
                self.requests.append(request)
                return http_error(429, "slow down")
            return Router.send(self, request)

    router = Limited(lambda request: None)
    envelope, _ = run(monkeypatch, router, Search(default=[hit()]), max_extra_searches=1)
    assert_fails_closed(envelope)


def test_unparseable_verifier_answer_does_not_keep_the_bank_claim(monkeypatch):
    envelope, _ = run_with(monkeypatch, lambda request: "это не JSON")
    assert_fails_closed(envelope)


def test_empty_verdicts_do_not_keep_the_bank_claim(monkeypatch):
    envelope, _ = run_with(monkeypatch, lambda request: {"verdicts": []})
    assert_fails_closed(envelope)


def test_unknown_verdict_value_does_not_keep_the_bank_claim(monkeypatch):
    envelope, _ = run_with(
        monkeypatch, lambda request: {"verdicts": [{"claim": 1, "verdict": "maybe", "reason": "?"}]}
    )
    assert_fails_closed(envelope)
    assert "неизвестный вердикт" in envelope["trace"]["checks"][0]["rejected_bank_claims"][0]["reason"]


def test_verdict_for_another_claim_number_does_not_keep_the_claim(monkeypatch):
    envelope, _ = run_with(
        monkeypatch, lambda request: {"verdicts": [{"claim": 7, "verdict": "supported", "reason": "ok"}]}
    )
    assert_fails_closed(envelope)


def test_explicit_supported_verdict_keeps_the_claim_with_its_source(monkeypatch):
    envelope, _ = run_with(
        monkeypatch, lambda request: {"verdicts": [{"claim": 1, "verdict": "supported", "reason": "ok"}]}
    )
    claims = envelope["result"]["bank_view"]
    assert claims and claims[0]["evidence_refs"]
    assert envelope["trace"]["checks"][0]["rejected_bank_claims"] == []


def test_unavailable_verifier_does_not_start_useless_repeat_searches(monkeypatch):
    envelope, _ = run_with(monkeypatch, lambda request: TransportFailure("timeout"))
    reasons = [item["code"] for item in envelope["trace"]["checks"][0]["reasons"]]
    assert "bank_verification_failed" in reasons
    assert envelope["trace"]["extra_searches"] == 0


def test_one_unverified_and_one_supported_claim_keep_only_the_supported_one(monkeypatch):
    two = {
        **GOOD,
        "bank_view": [
            {
                "text": "Альфа-Банк ожидает сохранения ставки на уровне 14,0% до конца года.",
                "evidence_ids": ["B1"],
            },
            {"text": "Альфа-Банк рекомендует немедленно закрыть компанию.", "evidence_ids": ["B1"]},
        ],
    }
    router = VerifierRouter(
        lambda request: {"verdicts": [{"claim": 1, "verdict": "supported", "reason": "ok"}]}
    )
    router.insight = [two]
    envelope, _ = run(monkeypatch, router, Search(default=[hit()]), max_extra_searches=1)
    texts = [claim["text"] for claim in envelope["result"]["bank_view"]]
    assert texts == ["Альфа-Банк ожидает сохранения ставки на уровне 14,0% до конца года."]
    rejected = envelope["trace"]["checks"][0]["rejected_bank_claims"]
    assert [item["verdict"] for item in rejected] == ["unverified"]

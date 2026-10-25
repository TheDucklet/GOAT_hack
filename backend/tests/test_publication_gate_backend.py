import copy

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_factory
from app.models import Chat, Insight, Message
from app.services.jobs import run_one
from tests import fake_ai, fake_feed_ai
from tests.factories import enable_ai, event_fixture, login
from tests.test_feed_snapshots import PATH, events, feed_ai, get_feed, prepared  # noqa: F401


def without_report(envelope):
    envelope = copy.deepcopy(envelope)
    envelope["trace"].pop("publication", None)
    return envelope


def blocked(envelope):
    envelope = copy.deepcopy(envelope)
    envelope["trace"]["publication"] = {
        **envelope["trace"]["publication"],
        "decision": "block",
        "stop_reason": "repair_failed",
    }
    return envelope


def changed_after_check(envelope):
    envelope = copy.deepcopy(envelope)
    envelope["result"]["unknowns"] = [*envelope["result"]["unknowns"], "добавлено после проверки"]
    return envelope


def old_policy(envelope):
    envelope = copy.deepcopy(envelope)
    envelope["trace"]["publication"] = {**envelope["trace"]["publication"], "policy_version": "publication-0"}
    return envelope


def model_decided(envelope):
    envelope = copy.deepcopy(envelope)
    envelope["trace"]["publication"] = {**envelope["trace"]["publication"], "decided_by": "model"}
    return envelope


def incomplete(envelope):
    envelope = copy.deepcopy(envelope)
    report = envelope["trace"]["publication"]
    report["claims"] = report["claims"][:-1]
    return envelope


BREAKERS = {
    "missing": (without_report, "invalid_publication_report"),
    "blocked": (blocked, "quality_gate_blocked"),
    "changed_after_check": (changed_after_check, "invalid_publication_report"),
    "old_policy": (old_policy, "invalid_publication_report"),
    "model_decided": (model_decided, "invalid_publication_report"),
    "incomplete": (incomplete, "invalid_publication_report"),
}


@pytest.mark.parametrize("name", BREAKERS)
def test_insight_without_a_valid_allowing_report_is_never_stored(client, monkeypatch, name):
    enable_ai(monkeypatch)
    breaker, code = BREAKERS[name]
    original = fake_ai.build_insight
    monkeypatch.setattr(fake_ai, "build_insight", lambda **kwargs: breaker(original(**kwargs)))
    login(client)
    event_id = event_fixture()
    job = client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).json()
    assert run_one()
    status = client.get(f"/jobs/{job['id']}").json()
    assert status["status"] == "failed" and status["error"]["code"] == code
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0


def ask(client, event_id):
    chat = client.post("/chats", json={"company_id": "demo_company_a", "event_id": event_id}).json()
    job = client.post(f"/chats/{chat['id']}/messages", json={"text": "Почему это важно?"}).json()
    assert run_one()
    return chat, client.get(f"/jobs/{job['id']}").json()


@pytest.mark.parametrize("name", ["missing", "blocked", "changed_after_check", "old_policy", "incomplete"])
def test_chat_answer_without_a_valid_allowing_report_is_never_stored(client, monkeypatch, name):
    enable_ai(monkeypatch)
    breaker, code = BREAKERS[name]
    original = fake_ai.answer_chat
    monkeypatch.setattr(fake_ai, "answer_chat", lambda *a, **k: breaker(original(*a, **k)))
    login(client)
    chat, status = ask(client, event_fixture())
    assert status["status"] == "failed" and status["error"]["code"] == code
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat["id"])) == 1


def test_chat_service_message_is_stored_without_analysis_and_without_evidence(client, monkeypatch):
    from app.publication_policy import PUBLICATION_POLICY_VERSION, SERVICE_ANSWER, content_digest

    enable_ai(monkeypatch)
    original = fake_ai.answer_chat

    def service(*args, **kwargs):
        envelope = copy.deepcopy(original(*args, **kwargs))
        envelope["result"] = {**envelope["result"], "answer": SERVICE_ANSWER, "evidence_refs": []}
        envelope["evidence"] = []
        envelope["trace"]["publication"] = {
            "policy_version": PUBLICATION_POLICY_VERSION,
            "decision": "service_message",
            "decided_by": "code",
            "content_digest": content_digest(envelope["result"]),
        }
        return envelope

    monkeypatch.setattr(fake_ai, "answer_chat", service)
    login(client)
    chat, status = ask(client, event_fixture())
    assert status["status"] == "done"
    with session_factory()() as db:
        message = db.scalar(select(Message).where(Message.chat_id == chat["id"], Message.role == "assistant"))
        assert message.text == SERVICE_ANSWER and message.result["evidence_refs"] == []
        assert db.get(Chat, chat["id"]) is not None


def test_service_message_that_still_cites_evidence_is_rejected(client, monkeypatch):
    from app.publication_policy import PUBLICATION_POLICY_VERSION, content_digest

    enable_ai(monkeypatch)
    original = fake_ai.answer_chat

    def forged(*args, **kwargs):
        envelope = copy.deepcopy(original(*args, **kwargs))
        envelope["trace"]["publication"] = {
            "policy_version": PUBLICATION_POLICY_VERSION,
            "decision": "service_message",
            "decided_by": "code",
            "content_digest": content_digest(envelope["result"]),
        }
        return envelope

    monkeypatch.setattr(fake_ai, "answer_chat", forged)
    login(client)
    _, status = ask(client, event_fixture())
    assert status["status"] == "failed" and status["error"]["code"] == "invalid_publication_report"


@pytest.mark.parametrize("name", ["missing", "blocked", "changed_after_check"])
def test_feed_never_shows_a_ready_card_without_a_valid_report(client, feed_ai, monkeypatch, name):  # noqa: F811
    breaker, _ = BREAKERS[name]
    original = fake_feed_ai.build_insight
    monkeypatch.setattr(fake_feed_ai, "build_insight", lambda **kwargs: breaker(original(**kwargs)))
    login(client)
    events(2)
    feed = prepared(client)
    assert not any(item["generation_status"] == "ready" for item in feed["items"])
    assert any(item["generation_status"] == "failed" for item in feed["items"])
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0


def test_cached_card_is_not_reused_after_the_policy_version_changes(monkeypatch):
    from app import publication_policy
    from app.services.generation_metadata import generation_versions

    monkeypatch.setenv("AI_MODULE", "app.ai.bridge")
    get_settings.cache_clear()
    before = generation_versions()
    monkeypatch.setattr(publication_policy, "PUBLICATION_POLICY_VERSION", "publication-next")
    assert generation_versions() != before
    get_settings.cache_clear()


def test_service_message_with_free_analytical_text_is_rejected_by_api_and_worker(client, monkeypatch):
    from app.publication_policy import PUBLICATION_POLICY_VERSION, content_digest

    enable_ai(monkeypatch)
    original = fake_ai.answer_chat

    def forged(*args, **kwargs):
        envelope = copy.deepcopy(original(*args, **kwargs))
        envelope["result"] = {
            **envelope["result"],
            "answer": "У компании есть действующий кредит и обязательство немедленно его погасить.",
            "evidence_refs": [],
        }
        envelope["evidence"] = []
        envelope["trace"]["publication"] = {
            "policy_version": PUBLICATION_POLICY_VERSION,
            "decision": "service_message",
            "decided_by": "code",
            "content_digest": content_digest(envelope["result"]),
        }
        return envelope

    monkeypatch.setattr(fake_ai, "answer_chat", forged)
    login(client)
    chat, status = ask(client, event_fixture())
    assert status["status"] == "failed" and status["error"]["code"] == "invalid_publication_report"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat["id"])) == 1


def clear_bindings(envelope):
    for entry in envelope["trace"]["publication"]["claims"]:
        entry["evidence"] = []
    return envelope


def stale_versions(envelope):
    for entry in envelope["trace"]["publication"]["claims"]:
        for ref in entry["evidence"]:
            ref["version"] = "stale"
    return envelope


def extra_binding(envelope):
    entry = envelope["trace"]["publication"]["claims"][0]
    entry["evidence"] = [*entry["evidence"], {"id": "foreign", "version": "x"}]
    return envelope


def no_verifier_version(envelope):
    envelope["trace"]["publication"].pop("verifier_prompt_version", None)
    return envelope


def wrong_statement_type(envelope):
    envelope["trace"]["publication"]["claims"][0]["statement_type"] = "scenario"
    return envelope


@pytest.mark.parametrize(
    "breaker",
    [clear_bindings, stale_versions, extra_binding, no_verifier_version, wrong_statement_type],
)
def test_publication_report_must_bind_every_claim_to_the_exact_current_evidence(client, monkeypatch, breaker):
    enable_ai(monkeypatch)
    original = fake_ai.build_insight
    monkeypatch.setattr(fake_ai, "build_insight", lambda **kwargs: breaker(original(**kwargs)))
    login(client)
    event_id = event_fixture()
    job = client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).json()
    assert run_one()
    status = client.get(f"/jobs/{job['id']}").json()
    assert status["status"] == "failed" and status["error"]["code"] == "invalid_publication_report"

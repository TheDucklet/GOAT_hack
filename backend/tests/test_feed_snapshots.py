from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_factory
from app.integrations.ai import AIError
from app.models import (
    BankDocument,
    Company,
    Event,
    FeedDismissal,
    FeedSnapshot,
    Insight,
    Job,
    Membership,
    Source,
    User,
)
from app.services import feed_snapshots
from app.services.feed_ranking import runtime_result, score_preview
from app.services.generation_metadata import generation_versions
from app.services.jobs import run_one
from app.services.news import add_publication
from tests import fake_feed_ai
from tests.factories import event_fixture, login

PATH = "/companies/demo_company_a/feed"
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


@pytest.fixture
def feed_ai(monkeypatch):
    monkeypatch.setenv("AI_MODULE", "tests.fake_feed_ai")
    monkeypatch.setenv("FEED_PREPARE_TOP_K", "2")
    monkeypatch.setenv("FEED_CANDIDATE_LIMIT", "10")
    get_settings.cache_clear()
    monkeypatch.setattr(feed_snapshots, "utcnow", lambda: NOW)
    counts = []
    original = fake_feed_ai.build_insight

    def counted(*args, **kwargs):
        counts.append(kwargs["event"]["id"])
        return original(*args, **kwargs)

    monkeypatch.setattr(fake_feed_ai, "build_insight", counted)
    return counts


def events(count):
    first = event_fixture()
    with session_factory()() as db, db.begin():
        source = db.get(Source, "cbr")
        for number in range(1, count):
            add_publication(
                db,
                source,
                dict(
                    url=f"https://www.cbr.ru/press/test/{number + 1}",
                    title=f"Отдельное событие номер {number + 1}",
                    text=f"Independent synthetic source content {number + 1}",
                    published_at=NOW - timedelta(days=number),
                ),
            )
    return first


def get_feed(client, **params):
    response = client.get(PATH, params={"contract_version": "v2", **params})
    assert response.status_code == 200, response.text
    return response.json()


def prepared(client):
    queued = get_feed(client)
    assert run_one()
    return get_feed(client, snapshot_id=queued["snapshot_id"])


def test_get_is_offline_and_repeated_pages_share_one_job(client, feed_ai, monkeypatch):
    events(7)
    login(client)

    def forbidden(*args, **kwargs):
        raise AssertionError("generation must never run inside GET")

    monkeypatch.setattr(fake_feed_ai, "derive_user_focus", forbidden)
    monkeypatch.setattr(fake_feed_ai, "build_insight", forbidden)
    original = get_feed(client, limit=2)
    assert original["generation_status"] == "queued" and original["items"] == []
    for limit in [1, 2, 5]:
        assert get_feed(client, limit=limit)["snapshot_id"] == original["snapshot_id"]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.scalar(select(func.count()).select_from(FeedSnapshot)) == 1
    assert feed_ai == []


def test_worker_is_bounded_and_returns_real_saved_v2_previews(client, feed_ai):
    events(7)
    login(client)
    result = prepared(client)
    assert len(feed_ai) == 2
    assert result["generation_status"] == "ready"
    ready = [item for item in result["items"] if item["generation_status"] == "ready"]
    assert len(ready) == 2
    assert len([item for item in result["items"] if item["generation_status"] == "not_requested"]) == 5
    for item in ready:
        assert item["personalized_summary"]["evidence_refs"]
        assert client.get(f"/insights/{item['insight_id']}").json()["stale"] is False
        assert {"prompt", "model", "focus", "corpus", "event", "profile", "semantics", "contract"} <= item[
            "versions"
        ].keys()
    assert get_feed(client)["snapshot_id"] == result["snapshot_id"]
    assert not run_one()


def test_failed_and_budget_deferred_are_never_ready(client, feed_ai, monkeypatch):
    events(5)
    login(client)

    def exhausted(*args, **kwargs):
        raise AIError("budget_exhausted", "Synthetic budget limit")

    monkeypatch.setattr(fake_feed_ai, "build_insight", exhausted)
    result = prepared(client)
    assert result["generation_status"] == "deferred"
    assert all(
        item["generation_status"] == "deferred" and item["insight_id"] is None for item in result["items"]
    )
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0
    assert get_feed(client)["snapshot_id"] == result["snapshot_id"]
    assert not run_one()


def test_v1_producer_cannot_be_published_as_ready_v2(client, feed_ai, monkeypatch):
    from tests.fake_ai import build_insight

    monkeypatch.setattr(fake_feed_ai, "build_insight", build_insight)
    events(1)
    login(client)
    result = prepared(client)
    assert result["generation_status"] == "failed"
    assert result["items"][0]["generation_status"] == "failed"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0


def test_snapshot_rechecks_company_and_user_access(client, feed_ai):
    events(1)
    login(client)
    original = prepared(client)
    login(client, "user_b")
    assert (
        client.get(
            PATH, params={"contract_version": "v2", "snapshot_id": original["snapshot_id"]}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/companies/demo_company_b/feed",
            params={"contract_version": "v2", "snapshot_id": original["snapshot_id"]},
        ).status_code
        == 403
    )
    with session_factory()() as db, db.begin():
        user = db.scalar(select(User).where(User.email == "user_b@goat.example.org"))
        db.add(Membership(user_id=user.id, company_id="demo_company_a", status="active"))
    assert (
        client.get(
            PATH, params={"contract_version": "v2", "snapshot_id": original["snapshot_id"]}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "change", ["profile", "focus", "corpus", "generation", "semantics", "event", "summary"]
)
def test_changed_versions_mark_saved_preview_stale(client, feed_ai, monkeypatch, change):
    event_id = events(1)
    login(client)
    result = prepared(client)
    insight_id = result["items"][0]["insight_id"]
    with session_factory()() as db, db.begin():
        company = db.get(Company, "demo_company_a")
        if change == "profile":
            company.profile_version = "updated"
        elif change == "semantics":
            company.data_semantics_version = "unknown-next-semantics"
        elif change == "focus":
            member = db.scalar(select(Membership).where(Membership.company_id == company.id))
            member.interests = ["Новый фокус"]
        elif change == "corpus":
            db.add(
                BankDocument(
                    filename="synthetic.pdf",
                    sha256="a" * 64,
                    version="a" * 64,
                    storage_key="synthetic.pdf",
                    page_count=1,
                    status="done",
                )
            )
        elif change == "event":
            db.get(Event, event_id).version = "updated"
        elif change == "summary":
            db.get(Event, event_id).summary = "Updated source summary"
    if change == "generation":
        monkeypatch.setenv("AI_GENERATION_VERSION", "updated")
        get_settings.cache_clear()
    stale = get_feed(client, snapshot_id=result["snapshot_id"])
    assert stale["stale"] is True and stale["generation_status"] == "stale"
    assert stale["items"][0]["generation_status"] == "stale"
    assert stale["items"][0]["personalized_summary"] is None
    assert client.get(f"/insights/{insight_id}").json()["stale"] is True
    assert get_feed(client)["snapshot_id"] != result["snapshot_id"]


def test_revoked_queued_profile_does_not_call_ai(client, feed_ai):
    events(1)
    login(client)
    queued = get_feed(client)
    with session_factory()() as db, db.begin():
        member = db.scalar(select(Membership).where(Membership.company_id == "demo_company_a"))
        member.status = "rejected"
    assert run_one()
    assert feed_ai == []
    assert client.get(f"/jobs/{queued['job_id']}").status_code == 403


def test_stale_queued_profile_does_not_call_ai(client, feed_ai):
    events(1)
    login(client)
    queued = get_feed(client)
    with session_factory()() as db, db.begin():
        db.get(Company, "demo_company_a").profile_version = "changed-before-worker"
    assert run_one()
    assert feed_ai == []
    assert get_feed(client, snapshot_id=queued["snapshot_id"])["generation_status"] == "stale"


def test_pagination_remains_frozen_when_news_arrives_or_item_is_hidden(client, feed_ai):
    events(6)
    login(client)
    snapshot = prepared(client)
    original_ids = [item["event_id"] for item in snapshot["items"]]
    first = get_feed(client, snapshot_id=snapshot["snapshot_id"], limit=2)
    with session_factory()() as db, db.begin():
        user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
        db.add(
            FeedDismissal(user_id=user.id, company_id="demo_company_a", event_id=original_ids[0], version="*")
        )
        source = db.get(Source, "cbr")
        add_publication(
            db,
            source,
            dict(
                url="https://www.cbr.ru/new",
                title="Совершенно новая публикация 812",
                text="New independent synthetic publication",
                published_at=NOW,
            ),
        )
    second = get_feed(client, snapshot_id=snapshot["snapshot_id"], limit=2, offset=2)
    assert [item["event_id"] for item in second["items"]] == original_ids[2:4]
    assert first["next_offset"] == 2 and second["total"] == 6
    assert original_ids[0] not in [
        item["event_id"] for item in get_feed(client, snapshot_id=snapshot["snapshot_id"])["items"]
    ]
    with session_factory()() as db:
        assert db.get(Event, original_ids[0]).visible is True


def test_saved_long_lived_insight_is_not_expired_by_source_age(client, feed_ai):
    event_id = events(1)
    with session_factory()() as db, db.begin():
        db.get(Event, event_id).published_at = NOW - timedelta(days=400)
    login(client)
    snapshot = prepared(client)
    item = snapshot["items"][0]
    assert item["generation_status"] == "ready" and item["relevance_status"] == "active"
    assert item["rank_score"] >= 32


def test_review_expiry_and_bank_dates_are_independent_from_news_age(client, feed_ai):
    events(1)
    login(client)
    item = prepared(client)["items"][0]
    with session_factory()() as db, db.begin():
        insight = db.get(Insight, item["insight_id"])
        insight.result = {**insight.result, "valid_until": "2026-10-24", "review_after": "2026-10-23"}
    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(feed_snapshots, "utcnow", lambda: datetime(2026, 10, 22, 21, tzinfo=UTC))
        assert (
            client.get(f"/insights/{item['insight_id']}").json()["result"]["relevance_status"]
            == "review_required"
        )
        monkey.setattr(feed_snapshots, "utcnow", lambda: datetime(2026, 10, 24, 21, tzinfo=UTC))
        assert client.get(f"/insights/{item['insight_id']}").json()["result"]["relevance_status"] == "expired"
    finally:
        monkey.undo()
    value = dict(
        schema_version="v2",
        relevance_status="active",
        bank_view_context=dict(status="current", document_dates=["2020-01-01"]),
    )
    assert runtime_result(value, date(2026, 10, 22))["bank_view_context"]["status"] == "historical"


def test_application_weights_require_evidence_and_ignore_generated_numbers():
    value = dict(
        schema_version="v2",
        impact_level="high",
        relevance_status="active",
        impact_reason=dict(evidence_refs=[]),
        relevance_reason=dict(evidence_refs=[]),
        personalized_summary=dict(text="100000 arbitrary points"),
    )
    score, _ = score_preview(1, [], value, date(2026, 10, 22))
    assert score == 1


def test_model_and_prompt_identity_change_automatically(monkeypatch):
    from app.ai.impact import prompts
    from app.ai.providers.settings import get_llm_settings

    monkeypatch.setenv("AI_MODULE", "app.ai.bridge")
    get_settings.cache_clear()
    original = generation_versions()
    runtime = get_llm_settings()
    monkeypatch.setattr(
        runtime, "llm_task_models", {**runtime.llm_task_models, "build_impact": "synthetic/model-2"}
    )
    assert generation_versions()["model"] != original["model"]
    monkeypatch.setattr(prompts, "IMPACT_PROMPT_VERSION", "synthetic-prompt-2")
    assert generation_versions()["prompt"] != original["prompt"]


def test_two_focuses_have_separate_snapshots_and_different_top_candidates(client, feed_ai, monkeypatch):
    monkeypatch.setenv("FEED_PREPARE_TOP_K", "1")
    get_settings.cache_clear()
    events(2)
    login(client)
    with session_factory()() as db, db.begin():
        items = list(db.scalars(select(Event).order_by(Event.id)))
        items[0].topics, items[1].topics = {"topic": ["A"]}, {"topic": ["B"]}
        ids = [item.id for item in items]
        member = db.scalar(select(Membership).where(Membership.company_id == "demo_company_a"))
        member.interests = ["A"]
    first = prepared(client)
    assert first["items"][0]["event_id"] == ids[0]
    with session_factory()() as db, db.begin():
        member = db.scalar(select(Membership).where(Membership.company_id == "demo_company_a"))
        member.interests = ["B"]
    second = prepared(client)
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["items"][0]["event_id"] == ids[1]


def test_postgres_concurrent_gets_share_one_snapshot_and_job(client, feed_ai):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.db import get_engine

    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL row lock and unique constraint concurrency")
    events(1)
    login(client)
    barrier = Barrier(2)

    def request():
        with session_factory()() as db:
            user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
            barrier.wait(timeout=10)
            snapshot = feed_snapshots.request_snapshot(db, user, "demo_company_a")
            snapshot_id = snapshot.id
            db.commit()
            return snapshot_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: request(), range(2)))
    assert ids[0] == ids[1]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(FeedSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_active_saved_card_survives_the_latest_news_window(client, feed_ai):
    event_id = events(1)
    with session_factory()() as db, db.begin():
        db.get(Event, event_id).published_at = NOW - timedelta(days=400)
    login(client)
    prepared(client)
    with session_factory()() as db, db.begin():
        db.add_all(
            Event(
                title=f"New event {number}",
                normalized_title=f"New event {number}",
                published_at=NOW,
                version="1",
            )
            for number in range(2001)
        )
    queued = get_feed(client)
    with session_factory()() as db:
        snapshot = db.get(FeedSnapshot, queued["snapshot_id"])
        assert event_id in [candidate["event_id"] for candidate in snapshot.candidates]
        assert len(snapshot.candidates) == 10


def test_shared_feed_examples_and_schema_match_the_canonical_model():
    import importlib.util
    import json
    from pathlib import Path

    from app.schemas import FeedSnapshotOut

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("export_feed", root / "scripts/export_feed_contracts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, artifact in module.artifacts().items():
        assert json.loads((root / "docs/contracts" / name).read_text(encoding="utf-8")) == artifact
    for example in module.artifacts()["feed-snapshot-v2-examples.json"]:
        FeedSnapshotOut.model_validate(example["data"])

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import BankDocument, Company, Event, Insight, Job
from app.services.jobs import claim_next, enqueue, run_one
from tests.conftest import login
from tests.test_backend import enable_ai, event_fixture


@pytest.mark.parametrize("dimension", ["profile", "event", "generation", "corpus"])
def test_insight_cache_versions(client, monkeypatch, dimension):
    enable_ai(monkeypatch)
    login(client)
    event_id = event_fixture()
    result = client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert run_one()
    assert client.get(f"/jobs/{result.json()['id']}").json()["status"] == "done"
    assert client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).status_code == 200
    if dimension == "generation":
        monkeypatch.setenv("AI_GENERATION_VERSION", "2")
        get_settings.cache_clear()
    else:
        with session_factory()() as db, db.begin():
            if dimension == "profile":
                db.get(Company, "demo_company_a").profile_version = "demo-v2"
            elif dimension == "event":
                db.get(Event, event_id).version = "event-v2"
            else:
                db.add(
                    BankDocument(
                        filename="test.pdf",
                        sha256="0" * 64,
                        version="v1",
                        index_version="ocr-v2",
                        storage_key="test.pdf",
                        page_count=1,
                    )
                )
    assert client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).status_code == 202


def test_invalid_ai_evidence_rolls_back_all_outputs(client, monkeypatch):
    enable_ai(monkeypatch)
    from tests import fake_ai

    original = fake_ai.build_insight

    def bad_result(**kwargs):
        result = original(**kwargs)
        result["result"]["facts"][0]["evidence_refs"] = ["nonexistent"]
        return result

    monkeypatch.setattr(fake_ai, "build_insight", bad_result)
    login(client)
    event_id = event_fixture()
    job = client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).json()
    assert run_one()
    status = client.get(f"/jobs/{job['id']}").json()
    assert status["status"] == "failed" and status["error"]["code"] == "invalid_evidence"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0


def test_job_retries_are_bounded(env, monkeypatch):
    from app.integrations.ai import AIError
    from app.services import jobs

    def fail(*_):
        raise AIError("timeout", "Temporary test timeout")

    monkeypatch.setattr(jobs, "execute_job", fail)
    with session_factory()() as db, db.begin():
        job = enqueue(db, "collect_news", {}, dedup_key="collect_news")
        job_id = job.id
    for attempt in [1, 2, 3]:
        assert run_one()
        with session_factory()() as db, db.begin():
            job = db.get(Job, job_id)
            assert job.attempts == attempt
            assert job.status == ("queued" if attempt < 3 else "failed")
            job.available_at = utcnow() - timedelta(seconds=1)
    assert run_one() is False


def test_parallel_worker_claims_are_distinct(env):
    from concurrent.futures import ThreadPoolExecutor

    with session_factory()() as db, db.begin():
        enqueue(db, "collect_news", {})
        enqueue(db, "collect_news", {})

    def claim():
        with session_factory()() as db:
            return claim_next(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: claim(), range(2)))
    if get_settings().database_url.startswith("postgresql"):
        assert len(set(ids)) == 2 and None not in ids
    else:
        assert len([key for key in ids if key]) == len(set(key for key in ids if key))


def test_revoked_membership_prevents_pending_ai_job(client, monkeypatch):
    enable_ai(monkeypatch)
    user = login(client)
    event_id = event_fixture()
    job = client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).json()
    login(client, "admin")
    client.patch(f"/admin/memberships/{user['memberships'][0]['id']}", json={"status": "rejected"})
    assert run_one()
    with session_factory()() as db:
        assert db.get(Job, job["id"]).error["code"] == "forbidden"
        assert db.scalar(select(func.count()).select_from(Insight)) == 0

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.db import get_engine, session_factory
from app.models import Chunk, Job
from app.services.jobs import run_one
from app.services.queue import enqueue
from tests.factories import enable_ai, event_fixture, login, pdf_bytes


def test_material_retries_reuse_active_jobs_and_preserve_running_status(client):
    login(client, "admin")
    event_id = event_fixture()
    document = client.post("/admin/documents", files={"file": ("synthetic.pdf", pdf_bytes())}).json()
    for path in [
        f"/admin/documents/{document['document']['id']}/reindex",
        f"/admin/news/{event_id}/retry",
        "/admin/jobs/collect-news",
    ]:
        first = client.post(path)
        second = client.post(path)
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
    job_id = client.post(f"/admin/news/{event_id}/retry").json()["id"]
    with session_factory()() as db, db.begin():
        db.get(Job, job_id).status = "running"
    assert client.post(f"/admin/news/{event_id}/retry").json()["status"] == "running"
    row = next(row for row in client.get("/admin/news").json() if row["id"] == event_id)
    assert row["processing_status"] == "running"


def test_indexed_document_returns_persisted_page_evidence_and_duplicate_upload_needs_no_job(
    client, monkeypatch
):
    enable_ai(monkeypatch)
    login(client, "admin")
    pdf = pdf_bytes()
    uploaded = client.post("/admin/documents", files={"file": ("synthetic.pdf", pdf)}).json()
    assert run_one()
    job = client.get(f"/jobs/{uploaded['job']['id']}").json()
    assert job["status"] == "done"
    source = client.get(f"/sources/{job['result']['source_id']}").json()
    assert source["source_id"] == uploaded["document"]["id"]
    assert source["locator"]["page"] == 1 and source["excerpt"]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Chunk)) > 0
        count = db.scalar(select(func.count()).select_from(Job))
    repeated = client.post("/admin/documents", files={"file": ("same.pdf", pdf)}).json()
    assert repeated["document"]["id"] == uploaded["document"]["id"]
    assert repeated["job"] is None and repeated["source_id"] == source["id"]
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == count


def test_admin_job_metadata_has_only_safe_material_target_and_is_admin_only(client):
    login(client, "admin")
    event = event_fixture()
    accepted = client.post(f"/admin/news/{event}/retry").json()
    with session_factory()() as db, db.begin():
        enqueue(db, "chat", {"chat_id": "private-chat", "text": "private text"})
    rows = client.get("/admin/jobs").json()
    assert next(row for row in rows if row["id"] == accepted["id"])["target_id"] == event
    other = next(row for row in rows if row["kind"] == "chat")
    assert other["target_id"] is None and "payload" not in other
    login(client)
    for path in ["/admin/jobs", "/admin/news", "/admin/documents"]:
        assert client.get(path).status_code == 403


def test_hidden_news_is_excluded_from_feed_for_all_users(client):
    event = event_fixture()
    login(client)
    assert any(
        row["event_id"] == event for row in client.get("/companies/demo_company_a/feed").json()["items"]
    )
    login(client, "admin")
    assert client.patch(f"/admin/news/{event}", json={"visible": False}).json()["visible"] is False
    login(client)
    assert all(
        row["event_id"] != event for row in client.get("/companies/demo_company_a/feed").json()["items"]
    )
    login(client, "user_b")
    assert all(
        row["event_id"] != event for row in client.get("/companies/demo_company_b/feed").json()["items"]
    )


def test_enqueue_remains_inside_the_callers_transaction(env):
    with session_factory()() as db:
        job = enqueue(db, "collect_news", {}, dedup_key="rollback-material")
        job_id = job.id
        db.rollback()
    with session_factory()() as db:
        assert db.get(Job, job_id) is None


def test_postgres_simultaneous_enqueue_reuses_one_material_job(env):
    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL unique-key concurrency")
    barrier = Barrier(2)

    def submit(_):
        with session_factory()() as db:
            barrier.wait(timeout=10)
            job = enqueue(db, "collect_news", {}, dedup_key="parallel-material")
            job_id = job.id
            db.commit()
            return job_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(submit, range(2)))
    assert ids[0] == ids[1]

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import session_factory, utcnow
from app.errors import AppError
from app.models import BankDocument, Chunk, Job, User
from app.services.jobs import scheduler_tick
from app.services.tools import AnalysisTools, BankRepository
from tests.factories import event_fixture


def test_agent_tools_cannot_select_another_company(env):
    event_id = event_fixture()
    with session_factory()() as db:
        user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
        tools = AnalysisTools(db, user.id, "demo_company_a", event_id)
        assert tools.get_company_context()["company_id"] == "demo_company_a"
        with pytest.raises(AppError) as error:
            tools.get_company_context("demo_company_b")
        assert error.value.status == 403


def test_bank_repository_date_filter_and_source_locators(env):
    with session_factory()() as db, db.begin():
        for name, day in [("old", "2026-01-01"), ("future", "2027-01-01"), ("unknown", None)]:
            doc = BankDocument(
                filename=f"{name}.pdf",
                sha256=name,
                version="1",
                document_date=day,
                storage_key=f"{name}.pdf",
                status="done",
                page_count=1,
            )
            db.add(doc)
            db.flush()
            db.add(Chunk(document_id=doc.id, version="1", page=1, text="инфляция ставка"))
    with session_factory()() as db:
        result = BankRepository(db).search_chunks("инфляция", "2026-10-20")
        assert len(result) == 2
        assert {r["document_date"] for r in result} == {None, "2026-01-01"}
        assert all(r["page"] == 1 and r["text"] for r in result)
        assert BankRepository(db).search_chunks("несуществующийзапрос", "2026-10-20") == []


def test_scheduler_repeats_on_interval_and_marks_lost_worker(env):
    with session_factory()() as db, db.begin():
        document = BankDocument(
            filename="lost.pdf",
            sha256="lost",
            version="1",
            storage_key="lost.pdf",
            page_count=1,
            status="running",
        )
        db.add(document)
        db.flush()
        document_id = document.id
        job = Job(kind="collect_news", status="done", created_at=utcnow() - timedelta(minutes=30))
        lost = Job(
            kind="ingest_document",
            payload={"document_id": document_id},
            status="running",
            started_at=utcnow() - timedelta(hours=2),
        )
        db.add_all([job, lost])
        db.flush()
        lost_id = lost.id
    with session_factory()() as db, db.begin():
        scheduler_tick(db)
        lost = db.get(Job, lost_id)
        assert lost.status == "failed" and lost.error["code"] == "worker_lost"
        assert db.get(BankDocument, document_id).status == "failed"
        assert db.scalar(select(Job).where(Job.status == "queued", Job.kind == "collect_news"))

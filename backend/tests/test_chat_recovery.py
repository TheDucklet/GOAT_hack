from sqlalchemy import func, select

from app.db import session_factory
from app.models import BankDocument, Event, Evidence, Job, Membership, Message, User
from app.services.jobs import run_one
from tests.factories import enable_ai, event_fixture, login


def conversation(client):
    event = event_fixture()
    login(client)
    response = client.post("/chats", json={"company_id": "demo_company_a", "event_id": event})
    assert response.status_code == 201
    return response.json(), f"/chats/{response.json()['id']}"


def test_chat_restore_returns_owned_context_and_last_job(client, monkeypatch):
    enable_ai(monkeypatch)
    chat, path = conversation(client)
    body = {"text": "Почему это важно?", "client_message_id": "question-001"}
    first = client.post(path + "/messages", json=body)
    duplicate = client.post(path + "/messages", json=body)
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["id"] == duplicate.json()["id"]
    state = client.get(path).json()
    assert state["company_id"] == chat["company_id"] and state["event_id"] == chat["event_id"]
    assert state["event_title"] and state["last_job"]["id"] == first.json()["id"]
    assert state["last_client_message_id"] == "question-001"
    assert run_one()
    assert client.post(path + "/messages", json=body).json()["id"] == first.json()["id"]
    assert len(client.get(path + "/messages").json()) == 2
    assert client.post(path + "/messages", json={**body, "text": "Другой текст"}).status_code == 409
    login(client, "user_b")
    assert client.get(path).status_code == 403


def test_manual_failed_retry_reuses_question_and_does_not_duplicate_messages(client, monkeypatch):
    chat, path = conversation(client)
    body = {"text": "Каких данных не хватает?", "client_message_id": "question-002"}
    first = client.post(path + "/messages", json=body).json()
    assert run_one()  # AI is deliberately unavailable.
    assert client.get(path).json()["last_job"]["status"] == "failed"
    assert client.post(path + "/messages", json=body).json()["id"] == first["id"]
    enable_ai(monkeypatch)
    retried = client.post(path + "/messages", json={**body, "retry": True}).json()
    assert retried["id"] != first["id"]
    assert client.post(path + "/messages", json={**body, "retry": True}).json()["id"] == retried["id"]
    assert run_one()
    with session_factory()() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.chat_id == chat["id"], Message.role == "user")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "chat")) == 2
    assert len(client.get(path + "/messages").json()) == 2


def test_restore_rechecks_membership_visibility_and_foreign_user_with_same_company(client):
    chat, path = conversation(client)
    with session_factory()() as db, db.begin():
        other = db.scalar(select(User).where(User.email == "user_b@goat.example.org"))
        db.add(Membership(user_id=other.id, company_id=chat["company_id"], status="active"))
    login(client, "user_b")
    assert client.get(path).status_code == 403
    login(client)
    with session_factory()() as db, db.begin():
        db.get(Event, chat["event_id"]).visible = False
    assert client.get(path).status_code == 404


def test_question_keys_do_not_escape_chat_scope_and_require_csrf(client):
    chat, path = conversation(client)
    second = client.post(
        "/chats", json={"company_id": chat["company_id"], "event_id": chat["event_id"]}
    ).json()
    body = {"text": "Вопрос", "client_message_id": "same-client-key"}
    one = client.post(path + "/messages", json=body).json()
    two = client.post(f"/chats/{second['id']}/messages", json=body).json()
    assert one["id"] != two["id"]
    client.headers.pop("X-CSRF-Token")
    assert client.post(path + "/messages", json={**body, "retry": True}).status_code == 403


def test_legacy_failed_question_can_be_retried_without_copying_the_message(client, monkeypatch):
    _, path = conversation(client)
    body = {"text": "Старый вопрос без ключа"}
    client.post(path + "/messages", json=body)
    assert run_one()
    state = client.get(path).json()
    assert state["last_client_message_id"].startswith("legacy_")
    enable_ai(monkeypatch)
    client.post(
        path + "/messages", json={**body, "client_message_id": state["last_client_message_id"], "retry": True}
    )
    assert run_one()
    assert len(client.get(path + "/messages").json()) == 2


def test_bank_evidence_reports_history_and_changed_versions(client):
    login(client)
    with session_factory()() as db, db.begin():
        db.add(
            BankDocument(
                id="old-doc",
                filename="synthetic.pdf",
                sha256="a" * 64,
                version="old",
                storage_key="old.pdf",
                page_count=3,
                document_date="2024-06-01",
                status="done",
            )
        )
        db.add(
            Evidence(
                id="old-bank",
                kind="bank",
                source_id="old-doc",
                version="old",
                locator={"page": 3, "document_date": "2024-06-01"},
                excerpt="Учебный материал",
            )
        )
    source = client.get("/sources/old-bank").json()
    assert source["locator"]["temporal_status"] == "historical"
    assert source["locator"]["document_date"] == "2024-06-01"
    with session_factory()() as db, db.begin():
        db.get(BankDocument, "old-doc").version = "new"
    assert client.get("/sources/old-bank").json()["locator"]["temporal_status"] == "source_changed"
    assert client.get("/sources/old-bank/file").status_code == 409


def test_postgres_parallel_question_submission_reuses_one_message_and_job(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import pytest

    from app.db import get_engine
    from app.schemas import MessageIn
    from app.services.chats import submit_question

    if get_engine().dialect.name != "postgresql":
        pytest.skip("PostgreSQL chat row lock")
    chat, _ = conversation(client)
    barrier = Barrier(2)

    def submit():
        with session_factory()() as db:
            user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
            barrier.wait(timeout=10)
            _, message, job, _ = submit_question(
                db,
                user,
                chat["id"],
                MessageIn(text="Параллельный вопрос", client_message_id="concurrent-key"),
            )
            result = (message.id, job.id)
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        values = list(executor.map(lambda _: submit(), range(2)))
    assert values[0] == values[1]

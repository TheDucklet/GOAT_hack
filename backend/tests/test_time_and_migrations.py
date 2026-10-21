from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select, update

from app.cli import migrate
from app.config import get_settings
from app.db import as_utc, get_engine, session_factory, utcnow
from app.models import Chat, LoginSession, Message
from app.services.jobs import run_one
from tests.factories import enable_ai, event_fixture, login


def test_aware_time_is_converted_instead_of_relabelled():
    source = datetime(2026, 10, 20, 12, tzinfo=timezone(timedelta(hours=3)))
    assert as_utc(source) == datetime(2026, 10, 20, 9, tzinfo=UTC)


def test_expired_session_is_rejected_in_postgres_timezone(client):
    login(client)
    with session_factory()() as db, db.begin():
        db.execute(update(LoginSession).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert client.get("/me").status_code == 401


def test_chat_order_does_not_depend_on_timestamps(client, monkeypatch):
    enable_ai(monkeypatch)
    login(client)
    event_id = event_fixture()
    chat = client.post("/chats", json={"company_id": "demo_company_a", "event_id": event_id}).json()
    for text in ["Первый вопрос", "Второй вопрос"]:
        assert client.post(f"/chats/{chat['id']}/messages", json={"text": text}).status_code == 202
        assert run_one()
    with session_factory()() as db, db.begin():
        db.execute(
            update(Message)
            .where(Message.chat_id == chat["id"])
            .values(created_at=utcnow() + timedelta(days=1))
        )
    assert client.post(f"/chats/{chat['id']}/messages", json={"text": "Третий вопрос"}).status_code == 202
    assert run_one()
    history = client.get(f"/chats/{chat['id']}/messages").json()
    assert [m["sequence"] for m in history] == [1, 2, 3, 4, 5, 6]
    assert "Третий вопрос" in history[-1]["text"]


def test_empty_sqlite_can_be_migrated_and_upgraded_twice(tmp_path, monkeypatch):
    # A separate disposable file, never the configured PostgreSQL or a user's database.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration_test.db'}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    migrate()
    migrate()
    with session_factory()() as db:
        assert list(db.scalars(select(Chat))) == []
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


def test_populated_v1_migration_keeps_data_and_requires_provenance_reimport(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.services.clients import company_context

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'populated_v1.db'}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    try:
        command.upgrade(config, "0001")
        with get_engine().begin() as connection:
            connection.execute(
                text("""INSERT INTO companies
                (id,name,profile_version,features,unknowns,is_placeholder)
                VALUES ('old','old','old-profile','{"REVENUE_COMPANY":{"value":"1000"}}','[]',0)""")
            )
        command.upgrade(config, "head")
        command.check(config)
        with session_factory()() as db:
            context = company_context(db, "old")
            assert context["profile_version"] == "old-profile"
            assert context["data_semantics_version"] == "legacy-company-1"
            assert context["features"]["REVENUE_COMPANY"]["value"] is None
            assert "source_reimport_required" in context["unknowns"]
    finally:
        get_engine().dispose()
        get_engine.cache_clear()
        get_settings.cache_clear()

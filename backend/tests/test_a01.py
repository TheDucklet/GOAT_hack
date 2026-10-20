import json
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, text

from app import schemas
from app.config import get_settings
from app.contracts import OPERATIONS
from app.db import get_engine
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


def test_examples_validate():
    examples = json.loads((ROOT / "docs/contracts/examples.json").read_text(encoding="utf-8"))
    for example in examples:
        getattr(schemas, example["schema"]).model_validate(example["data"])
    assert {e["name"] for e in examples} >= {"pending_job", "error", "successful_user", "feed"}


def test_published_openapi_is_generated_from_current_contract(client):
    published = json.loads((ROOT / "docs/contracts/openapi.json").read_text(encoding="utf-8"))
    assert published == client.get("/openapi.json").json()


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda op: f"{op.method} {op.path}")
def test_every_operation_documents_access_request_response_and_pending_implementation(client, operation):
    schema = client.get("/openapi.json").json()
    item = schema["paths"][operation.path][operation.method.lower()]
    assert item["x-access"]["rule"] == operation.access
    assert item["x-implementation-status"] in {"contract-only", "implemented"}
    assert str(operation.status) in item["responses"]
    if item["x-implementation-status"] == "contract-only":
        assert "501" in item["responses"]
    if operation.body or operation.upload:
        assert item["requestBody"]["required"] is True
    if not operation.access.startswith("public;"):
        assert item["security"]
    assert item["x-access"]["csrf_required"] == (
        not operation.access.startswith("public;") and operation.method in {"POST", "PATCH"}
    )


def test_contract_operations_do_not_claim_business_functionality(client):
    schema = client.get("/openapi.json").json()
    pending = [
        op
        for op in OPERATIONS
        if op.method == "GET"
        and schema["paths"][op.path]["get"]["x-implementation-status"] == "contract-only"
    ]
    if not pending:
        return
    result = client.get(pending[0].path)
    assert result.status_code in {401, 403, 501}
    schemas.ErrorOut.model_validate(result.json())
    if result.status_code == 501:
        assert result.json()["code"] == "not_implemented"
    assert result.json()["request_id"] == result.headers["X-Request-ID"]


def test_position_is_free_text_and_public_registration_cannot_select_system_role(client):
    profile = schemas.ProfileIn(position_text="Руководитель нового направления без справочника")
    assert profile.position_text.startswith("Руководитель")
    response = client.post(
        "/auth/register",
        json={"email": "demo@example.org", "password": "synthetic-password", "system_role": "admin"},
    )
    assert response.status_code == 422
    schemas.ErrorOut.model_validate(response.json())
    with pytest.raises(ValidationError):
        schemas.UserOut(id="example", email="demo@example.org", system_role="owner", status="active")


def test_contract_includes_all_required_task_routes():
    methods = {(op.method, op.path) for op in OPERATIONS}
    required = {
        ("POST", "/auth/register"),
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("GET", "/me"),
        ("POST", "/memberships/requests"),
        ("PATCH", "/memberships/{membership_id}/profile"),
        ("GET", "/companies"),
        ("GET", "/companies/{company_id}/context"),
        ("GET", "/companies/{company_id}/feed"),
        ("POST", "/companies/{company_id}/insights"),
        ("POST", "/chats"),
        ("POST", "/chats/{chat_id}/messages"),
        ("GET", "/chats/{chat_id}/messages"),
        ("GET", "/jobs/{job_id}"),
        ("GET", "/sources/{source_id}"),
        ("GET", "/sources/{source_id}/file"),
        ("POST", "/feedback"),
        ("GET", "/admin/users"),
        ("PATCH", "/admin/users/{user_id}"),
        ("GET", "/admin/memberships"),
        ("PATCH", "/admin/memberships/{membership_id}"),
        ("GET", "/admin/documents"),
        ("POST", "/admin/documents"),
        ("POST", "/admin/documents/{document_id}/reindex"),
        ("GET", "/admin/news"),
        ("PATCH", "/admin/news/{event_id}"),
        ("POST", "/admin/news/{event_id}/retry"),
        ("GET", "/admin/jobs"),
        ("POST", "/admin/jobs/collect-news"),
        ("GET", "/admin/stats"),
    }
    assert required <= methods


def test_initial_migration_on_empty_database(tmp_path, monkeypatch):
    url = os.environ.get("A01_TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'a01_test.db'}")
    if not url.startswith("sqlite") and not url.split("?")[0].endswith("/goat_a01_test"):
        raise RuntimeError("Only a dedicated goat_a01_test database may be migrated by this check")
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    inspector = inspect(get_engine())
    assert {
        "users",
        "sessions",
        "companies",
        "memberships",
        "events",
        "bank_documents",
        "chunks",
        "evidence",
        "insights",
        "chats",
        "messages",
        "jobs",
        "feedback",
    } <= set(inspector.get_table_names())
    with get_engine().connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
    command.check(config)
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()

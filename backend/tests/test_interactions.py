import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import schemas
from app.db import session_factory, utcnow
from app.models import DemoAction, Event, Insight, Membership, ProductEvent, User
from app.services.interactions import product_metrics, purge_events, record_event
from tests.factories import event_fixture, login

COMPANY = "demo_company_a"
BASE = f"/companies/{COMPANY}"


@pytest.mark.parametrize(
    "example",
    json.loads(
        (Path(__file__).resolve().parents[2] / "docs/contracts/interaction-examples.json").read_text(
            encoding="utf-8"
        )
    ),
    ids=lambda item: item["name"],
)
def test_shared_interaction_examples(example):
    getattr(schemas, example["schema"]).model_validate(example["data"])


def card(user_id, event_id):
    with session_factory()() as db, db.begin():
        obj = Insight(
            user_id=user_id,
            company_id=COMPANY,
            event_id=event_id,
            cache_key="a" * 64,
            versions={"profile": "demo-v2"},
            result={},
        )
        db.add(obj)
        db.flush()
        return obj.id


def test_dismissal_is_private_persistent_and_reversible(client):
    event_id = event_fixture()
    user = login(client)
    body = {"event_id": event_id, "hidden": True}
    assert client.post(BASE + "/dismissals", json=body).status_code == 200
    assert client.post(BASE + "/dismissals", json=body).status_code == 200
    assert client.get(BASE + "/feed").json()["total"] == 0
    assert client.get(BASE + "/dismissals").json() == [{"event_id": event_id, "version": "*", "hidden": True}]
    login(client)
    assert client.get(BASE + "/feed").json()["total"] == 0
    with session_factory()() as db, db.begin():
        other = db.scalar(select(User).where(User.email == "user_b@goat.example.org"))
        db.add(
            Membership(
                user_id=other.id, company_id=COMPANY, status="active", position_text="Director", interests=[]
            )
        )
        assert db.get(Event, event_id).visible is True
    login(client, "user_b")
    assert client.get(BASE + "/feed").json()["total"] == 1
    login(client)
    assert client.post(BASE + "/dismissals", json={**body, "hidden": False}).json()["hidden"] is False
    assert client.get(BASE + "/feed").json()["total"] == 1
    assert user["id"]


def test_global_visibility_is_not_restored_by_personal_restore(client):
    event_id = event_fixture()
    login(client)
    with session_factory()() as db, db.begin():
        db.get(Event, event_id).visible = False
    assert client.post(BASE + "/dismissals", json={"event_id": event_id, "hidden": False}).status_code == 200
    assert client.get(BASE + "/feed").json()["total"] == 0


def test_version_dismissal_does_not_hide_all_future_versions(client):
    event_id = event_fixture()
    user = login(client)
    insight_id = card(user["id"], event_id)
    result = client.post(
        BASE + "/dismissals", json={"event_id": event_id, "insight_id": insight_id, "hidden": True}
    )
    assert result.json()["version"] == "a" * 64
    # The deliberately old card does not match current input versions.
    assert client.get(BASE + "/feed").json()["total"] == 1


def test_demo_action_is_idempotent_and_payload_bound(client):
    event_id = event_fixture()
    login(client)
    body = {"event_id": event_id, "action_type": "contact_manager", "idempotency_key": "operation-001"}
    first = client.post(BASE + "/demo-actions", json=body)
    login(client)
    second = client.post(BASE + "/demo-actions", json=body)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["mode"] == "demo" and first.json()["status"] == "recorded"
    with session_factory()() as db, db.begin():
        event = Event(title="Another", normalized_title="another")
        db.add(event)
        db.flush()
        another = event.id
    assert client.post(BASE + "/demo-actions", json={**body, "event_id": another}).status_code == 409
    assert client.post(BASE + "/demo-actions", json={**body, "action_type": "send_to_crm"}).status_code == 422
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(DemoAction)) == 1
        assert (
            db.scalar(
                select(func.count()).select_from(ProductEvent).where(ProductEvent.event_type == "action")
            )
            == 1
        )


def test_impressions_are_deduplicated_per_server_session_and_marked_test(client):
    event_id = event_fixture()
    user = login(client)
    insight_id = card(user["id"], event_id)
    body = {"event_id": event_id, "insight_id": insight_id, "event_type": "impression"}
    first = client.post(BASE + "/product-events", json=body).json()
    second = client.post(BASE + "/product-events", json=body).json()
    assert first["recorded"] is True and first["excluded_reason"] == "test"
    assert second["recorded"] is False and second["id"] == first["id"]
    login(client)
    assert client.post(BASE + "/product-events", json=body).json()["recorded"] is True
    with session_factory()() as db:
        assert product_metrics(db)["counts"]["impression"] == 0
        assert product_metrics(db)["open_rate"] is None


@pytest.mark.parametrize(
    "suffix,body",
    [
        ("/dismissals", {"hidden": True}),
        ("/demo-actions", {"action_type": "contact_manager", "idempotency_key": "test-operation"}),
        ("/product-events", {"insight_id": "no-card", "event_type": "impression"}),
    ],
)
def test_foreign_company_and_csrf_are_rejected(client, suffix, body):
    event_id = event_fixture()
    login(client, "user_b")
    assert client.post(BASE + suffix, json={**body, "event_id": event_id}).status_code == 403
    login(client)
    client.headers.pop("X-CSRF-Token")
    assert client.post(BASE + suffix, json={**body, "event_id": event_id}).status_code == 403


def test_foreign_card_is_rejected_even_with_company_access(client):
    event_id = event_fixture()
    user = login(client)
    insight_id = card(user["id"], event_id)
    with session_factory()() as db, db.begin():
        other = db.scalar(select(User).where(User.email == "user_b@goat.example.org"))
        db.add(
            Membership(
                user_id=other.id, company_id=COMPANY, status="active", position_text="Director", interests=[]
            )
        )
    login(client, "user_b")
    assert (
        client.post(
            BASE + "/dismissals", json={"event_id": event_id, "insight_id": insight_id, "hidden": True}
        ).status_code
        == 403
    )


def test_retention_and_bot_admin_exclusions(client):
    event_id = event_fixture()
    user = login(client)
    with session_factory()() as db, db.begin():
        actor = db.get(User, user["id"])
        actor.email = "human@customer.test"
        event = db.get(Event, event_id)
        old, _ = record_event(db, actor, COMPANY, event, None, "impression", "s1")
        old.created_at = utcnow() - timedelta(days=91)
        record_event(db, actor, COMPANY, event, None, "impression", "s2")
        record_event(db, actor, COMPANY, event, None, "open", "s2")
        bot, _ = record_event(db, actor, COMPANY, event, None, "impression", "s3", "crawler")
        assert bot.excluded_reason == "bot"
        actor.system_role = "admin"
        admin, _ = record_event(db, actor, COMPANY, event, None, "impression", "s4")
        assert admin.excluded_reason == "admin"
        assert purge_events(db) == 1
        metrics = product_metrics(db)
        assert metrics["counts"]["impression"] == 1 and metrics["open_rate"] == 1


def test_runtime_metrics_requires_admin(client):
    login(client)
    assert client.get("/admin/runtime-metrics").status_code == 403
    login(client, "admin")
    response = client.get("/admin/runtime-metrics")
    assert response.status_code == 200 and response.json()["budget"]["limit_rub"] == 500

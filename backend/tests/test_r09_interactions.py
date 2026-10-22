from sqlalchemy import func, select

from app.db import session_factory
from app.models import Event, Feedback, FeedDismissal
from tests.factories import event_fixture, login
from tests.test_interactions import BASE, card


def test_feedback_read_restores_rating_and_is_private(client):
    event = event_fixture()
    user = login(client)
    insight = card(user["id"], event)
    path = f"/insights/{insight}/feedback"
    assert client.get(path).json() is None
    body = {"insight_id": insight, "rating": 1}
    first = client.post("/feedback", json=body).json()
    assert client.post("/feedback", json=body).json() == first
    login(client)
    assert client.get(path).json() == first
    assert client.post("/feedback", json={**body, "rating": -1}).json()["id"] == first["id"]
    assert client.get(path).json()["rating"] == -1
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Feedback)) == 1
    login(client, "user_b")
    assert client.get(path).status_code in (403, 404)


def test_exact_version_restored_after_reload_and_details_are_opt_in(client):
    event = event_fixture()
    user = login(client)
    insight = card(user["id"], event)
    client.post(BASE + "/dismissals", json={"event_id": event, "insight_id": insight, "hidden": True})
    login(client)
    row = client.get(BASE + "/dismissals?include_details=true").json()[0]
    assert row["title"]
    assert set(client.get(BASE + "/dismissals").json()[0]) == {"event_id", "version", "hidden"}
    restore = {"event_id": event, "version": row["version"], "hidden": False}
    assert client.post(BASE + "/dismissals", json=restore).json() == {key: value for key, value in restore.items()}
    assert client.post(BASE + "/dismissals", json=restore).status_code == 200
    assert client.get(BASE + "/dismissals").json() == []
    assert client.post(BASE + "/dismissals", json={**restore, "hidden": True}).status_code == 422
    assert client.post(BASE + "/dismissals", json={**restore, "insight_id": insight}).status_code == 422
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(FeedDismissal)) == 0


def test_hidden_global_title_is_not_returned_by_personal_history(client):
    event = event_fixture()
    login(client)
    client.post(BASE + "/dismissals", json={"event_id": event, "hidden": True})
    with session_factory()() as db, db.begin():
        db.get(Event, event).visible = False
    assert "title" not in client.get(BASE + "/dismissals?include_details=true").json()[0]


def test_restore_version_cannot_delete_another_users_dismissal(client):
    event = event_fixture()
    login(client)
    client.post(BASE + "/dismissals", json={"event_id": event, "hidden": True})
    login(client, "user_b")
    assert client.post(BASE + "/dismissals", json={"event_id": event, "version": "*", "hidden": False}).status_code == 403
    login(client)
    assert len(client.get(BASE + "/dismissals").json()) == 1

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_factory
from app.main import create_app
from app.models import User


def test_registration_is_committed_before_http_response(env):
    app = create_app()
    committed_at_response = []
    email = "response.commit@example.org"

    async def observe_response(scope, receive, send):
        async def observe_send(message):
            if (
                message["type"] == "http.response.start"
                and scope.get("path") == "/auth/register"
                and message["status"] == 201
            ):
                with session_factory()() as db:
                    committed_at_response.append(
                        db.scalar(select(User.id).where(User.email == email)) is not None
                    )
            await send(message)

        await app(scope, receive, observe_send)

    with TestClient(observe_response) as client:
        result = client.post(
            "/auth/register", json={"email": email, "password": "Synthetic-Response-Test-2026"}
        )
        assert result.status_code == 201
    assert committed_at_response == [True]

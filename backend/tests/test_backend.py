from tests.conftest import PASSWORD


def test_auth_registration_logout_and_csrf(client):
    assert client.get("/me").status_code == 401
    assert client.get("/health").json() == {"status": "ok"}
    body = {"email": "new@example.org", "password": PASSWORD}
    assert client.post("/auth/register", json={**body, "system_role": "admin"}).status_code == 422
    assert client.post("/auth/register", json=body).status_code == 201
    assert client.post("/auth/register", json=body).status_code == 409
    assert client.post("/auth/login", json={**body, "password": "x"}).status_code == 401
    result = client.post("/auth/login", json=body)
    assert result.status_code == 200
    assert "password_hash" not in result.text
    assert "HttpOnly" in result.headers["set-cookie"]
    old_cookie = client.cookies.get("goat_session")
    assert client.post("/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set("goat_session", old_cookie)
    assert client.get("/me").status_code == 401

from tests.conftest import PASSWORD, login


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


def test_membership_approval_and_profile_do_not_grant_admin(client):
    client.post("/auth/register", json={"email": "new@example.org", "password": PASSWORD})
    result = client.post("/auth/login", json={"email": "new@example.org", "password": PASSWORD}).json()
    client.headers["X-CSRF-Token"] = result["csrf_token"]
    result = client.post("/memberships/requests", json={"company_id": "demo_company_a"})
    assert result.status_code == 201
    membership_id = result.json()["id"]
    assert client.get("/companies/demo_company_a/feed").status_code == 403
    assert client.get("/companies").json() == []
    login(client, "admin")
    assert client.patch(f"/admin/memberships/{membership_id}", json={"status": "active"}).status_code == 200
    result = client.post("/auth/login", json={"email": "new@example.org", "password": PASSWORD}).json()
    client.headers["X-CSRF-Token"] = result["csrf_token"]
    assert client.get("/companies").status_code == 200
    assert (
        client.patch(
            f"/memberships/{membership_id}/profile",
            json={"position_text": "Руководитель необычного направления", "interests": ["ставка"]},
        ).status_code
        == 200
    )
    assert client.get("/me").json()["system_role"] == "user"
    assert client.get("/admin/users").status_code == 403


def test_block_revokes_sessions(client):
    user = login(client)
    cookie = client.cookies.get("goat_session")
    login(client, "admin")
    assert client.patch(f"/admin/users/{user['id']}", json={"status": "blocked"}).status_code == 200
    client.cookies.clear()
    client.cookies.set("goat_session", cookie)
    assert client.get("/me").status_code == 401

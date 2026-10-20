import csv

import pytest
from sqlalchemy import func, select

from app.db import session_factory
from app.models import Company, Payment
from app.services.clients import company_context, import_clients
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
    assert client.get("/companies/demo_company_a/context").status_code == 200
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


def make_csvs(root):
    files = {
        "df_Uid_data_hack.csv": [
            ["SYNTHETIC_U", "GROUP_ID", "REGION", "MAINOKVED_CODE", "CL_PRODUCT_LOA_MARK"],
            ["u1", "g1", "Москва", "25.61", "1.0"],
            ["u1", "g2", "Москва", "25.62", "1.0"],
            ["u2", "g1", "", "25.61", "0.0"],
        ],
        "df_Fid_Uid_link_hack.csv": [
            ["SYNTHETIC_F", "CITY_NAME", "RC_NAME", "SYNTHETIC_U"],
            ["f1", "Москва", "Москва", "u1"],
            ["f1", "Москва", "Москва", "u2"],
        ],
        "df_Uid_payment_hack.csv": [
            ["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"],
            ["u2", "u1", "100.01", "5"],
            ["u2", "u1", "100.01", "5"],
            ["outside", "u1", "50.00", "2"],
        ],
    }
    for name, data in files.items():
        with (root / name).open("w", encoding="utf-8", newline="") as stream:
            csv.writer(stream, delimiter=";").writerows(data)


def test_import_idempotency_conflicts_unknown_counterparties_and_aggregates(env):
    make_csvs(env)
    with session_factory()() as db, db.begin():
        report = import_clients(db, env)
    assert report["company_rows"] == 3 and report["unique_companies"] == 2
    assert {c["field"] for c in report["conflicts"]} == {"GROUP_ID", "MAINOKVED_CODE"}
    with session_factory()() as db, db.begin():
        assert import_clients(db, env)["already_imported"] is True
        assert db.scalar(select(func.count()).select_from(Payment)) == 3
        ctx = company_context(db, "u1")
        assert ctx["group_id"] is None
        assert ctx["features"]["MAINOKVED_CODE"]["value"] is None
        assert ctx["payment_links"]["outgoing"][0]["amount"] == "200.02"
        assert ctx["payment_links"]["outgoing"][0]["payment_count"] == 10
        assert db.get(Company, "outside").is_placeholder
        assert "u2" in ctx["related_companies"]
    path = env / "df_Uid_payment_hack.csv"
    original = path.read_text()
    path.write_text(original.replace("50.00", "75.00"), encoding="utf-8")
    with session_factory()() as db, db.begin():
        assert import_clients(db, env)["already_imported"] is False
        assert db.scalar(select(func.count()).select_from(Payment)) == 3
    path.write_text(original, encoding="utf-8")
    with session_factory()() as db, db.begin():
        assert import_clients(db, env)["already_imported"] is False
        assert company_context(db, "u1")["payment_links"]["outgoing"][1]["amount"] == "50.00"


def test_import_invalid_numeric_rolls_back(env):
    make_csvs(env)
    path = env / "df_Uid_payment_hack.csv"
    path.write_text(path.read_text().replace("50.00", "NaN"), encoding="utf-8")
    with pytest.raises(ValueError), session_factory()() as db, db.begin():
        import_clients(db, env)
    with session_factory()() as db:
        assert db.get(Company, "u1") is None

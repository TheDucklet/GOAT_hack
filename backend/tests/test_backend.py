import csv
from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Company, Evidence, Feedback, Insight, Job, Payment, Source
from app.services.clients import company_context, import_clients
from app.services.jobs import claim_next, run_one, scheduler_tick
from app.services.news import add_publication, collect_news, ensure_sources, normalize_url
from app.services.ranking import rank_event
from tests.conftest import PASSWORD, login


def event_fixture():
    with session_factory()() as db, db.begin():
        ensure_sources(db)
        source = db.get(Source, "cbr")
        news, _ = add_publication(
            db,
            source,
            {
                "url": "https://www.cbr.ru/press/test/1",
                "title": "Решение по ключевой ставке",
                "text": "Подтвержденный текст новости о ставке.",
                "published_at": utcnow(),
            },
        )
        event_id = news.event_id
    return event_id


def enable_ai(monkeypatch):
    monkeypatch.setenv("AI_MODULE", "tests.fake_ai")
    get_settings.cache_clear()


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


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


def test_explainable_ranking_and_freshness(env):
    with session_factory()() as db:
        a, b = [company_context(db, f"demo_company_{suffix}") for suffix in ["a", "b"]]
    now = utcnow()
    event = {"topics": {"product": ["CL_PRODUCT_LOA_MARK"]}, "published_at": now}
    score, reasons = rank_event(a, {}, event, now)
    assert score > rank_event(b, {}, event, now)[0]
    assert reasons[0]["feature_path"] == "features.CL_PRODUCT_LOA_MARK"
    assert score > rank_event(a, {}, {**event, "published_at": now - timedelta(days=8)}, now)[0]
    assert rank_event(b, {}, {**event, "published_at": None}, now)[0] == 0


def test_news_deduplication_and_conservative_clustering(env):
    with session_factory()() as db, db.begin():
        ensure_sources(db)
        source = db.get(Source, "cbr")
        item = {
            "url": "https://www.cbr.ru/press/1?utm_source=test",
            "title": "Ставка сохранена 14%",
            "text": "Подтвержденный текст один",
            "published_at": utcnow(),
        }
        first, added = add_publication(db, source, item)
        assert added
        assert add_publication(db, source, item)[1] is False
        second, _ = add_publication(
            db,
            db.get(Source, "interfax"),
            {**item, "url": "https://www.interfax.ru/business/1", "text": "Текст другого источника"},
        )
        third, _ = add_publication(
            db,
            source,
            {
                **item,
                "url": "https://www.cbr.ru/press/2",
                "title": "Ставка сохранена 15%",
                "text": "Другое событие",
            },
        )
        assert first.event_id == second.event_id
        assert third.event_id != first.event_id
    with pytest.raises(ValueError):
        normalize_url("http://127.0.0.1/secrets", ["www.cbr.ru"])


def test_source_failure_does_not_stop_other_source(env):

    def handler(request):
        if request.url.host == "www.cbr.ru":
            return httpx.Response(503)
        return httpx.Response(
            200,
            content=b'<rss version="2.0"><channel><title>Test</title><item>\n            <title>Test event</title><link>https://www.interfax.ru/business/test</link>\n            <description>A source fact with enough text to avoid downloading any article. This is the text\n            of a synthetic publication used for the collection test only.</description></item></channel></rss>',
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        with session_factory()() as db, db.begin():
            result = collect_news(db, transport)
            assert result["cbr"]["ok"] is False
            assert result["interfax"]["added"] == 1
            assert collect_news(db, transport)["interfax"]["added"] == 0


def test_job_claim_and_scheduler_dedup(env):
    with session_factory()() as db, db.begin():
        scheduler_tick(db)
    with session_factory()() as db, db.begin():
        scheduler_tick(db)
        assert db.scalar(select(func.count()).select_from(Job)) == 1
    with session_factory()() as first, session_factory()() as second:
        job_id = claim_next(first)
        assert job_id is not None
        assert claim_next(second) is None


def test_ai_unavailable_is_failed_without_fake_answer(client):
    login(client)
    event_id = event_fixture()
    result = client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert result.status_code == 202
    assert run_one()
    status = client.get(f"/jobs/{result.json()['id']}").json()
    assert status["status"] == "failed" and status["error"]["code"] == "ai_unavailable"
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Insight)) == 0


def test_insight_chat_persistence_feedback_and_cache(client, monkeypatch):
    enable_ai(monkeypatch)
    login(client)
    event_id = event_fixture()
    result = client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert run_one()
    job = client.get(f"/jobs/{result.json()['id']}").json()
    assert job["status"] == "done", job
    insight_id = job["result"]["insight_id"]
    assert client.get(f"/insights/{insight_id}").json()["result"]["unknowns"] == ["loan_amount"]
    cached = client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert cached.status_code == 200 and cached.json()["id"] == insight_id
    for rating in [1, -1]:
        assert client.post("/feedback", json={"insight_id": insight_id, "rating": rating}).status_code == 200
    with session_factory()() as db:
        assert db.scalar(select(func.count()).select_from(Feedback)) == 1
    chat = client.post("/chats", json={"company_id": "demo_company_a", "event_id": event_id}).json()
    for question in ["Почему это важно нам?", "Каких данных не хватает?"]:
        response = client.post(f"/chats/{chat['id']}/messages", json={"text": question})
        assert response.status_code == 202
        assert client.post(f"/chats/{chat['id']}/messages", json={"text": question}).status_code == 409
        assert run_one()
    history = client.get(f"/chats/{chat['id']}/messages").json()
    assert len(history) == 4
    assert "Каких данных не хватает?" in history[-1]["text"]
    login(client, "admin")
    assert client.get("/admin/stats").json()["negative_feedback"] == 1


def test_cache_invalidates_on_profile_focus_and_event_change(client, monkeypatch):
    enable_ai(monkeypatch)
    user = login(client)
    event_id = event_fixture()
    client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert run_one()
    membership = user["memberships"][0]
    client.patch(f"/memberships/{membership['id']}/profile", json={"position_text": "Закупки"})
    assert client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).status_code == 202


def test_document_upload_dedup_protected_file_and_reindex(client, monkeypatch):
    data = pdf_bytes()
    login(client)
    assert client.post("/admin/documents", files={"file": ("x.pdf", data)}).status_code == 403
    login(client, "admin")
    assert client.post("/admin/documents", files={"file": ("x.pdf", b"not a pdf")}).status_code == 422
    result = client.post("/admin/documents", files={"file": ("../../x.pdf", data)})
    assert result.status_code == 202, result.text
    doc_id = result.json()["document"]["id"]
    repeat = client.post("/admin/documents", files={"file": ("x.pdf", data)})
    assert repeat.json()["document"]["id"] == doc_id
    assert run_one()
    assert client.get("/admin/documents").json()[0]["status"] == "failed"
    enable_ai(monkeypatch)
    retry = client.post(f"/admin/documents/{doc_id}/reindex")
    assert retry.status_code == 202
    assert run_one()
    assert client.get("/admin/documents").json()[0]["status"] == "done"
    with session_factory()() as db:
        evidence_id = db.scalar(select(Evidence.id).where(Evidence.kind == "bank"))
    locator = client.get(f"/sources/{evidence_id}").json()["locator"]
    assert locator["url"].endswith("#page=1")
    assert client.get(f"/sources/{evidence_id}/file").content == data
    client.post("/auth/logout")
    assert client.get(f"/sources/{evidence_id}/file").status_code == 401


def test_pdf_size_limit(client, monkeypatch):
    login(client, "admin")
    monkeypatch.setattr(get_settings(), "max_pdf_bytes", 10)
    assert client.post("/admin/documents", files={"file": ("x.pdf", pdf_bytes())}).status_code == 413


def test_hidden_news_excluded_from_feed(client):
    event_id = event_fixture()
    login(client, "admin")
    assert client.patch(f"/admin/news/{event_id}", json={"visible": False}).status_code == 200
    login(client)
    assert client.get("/companies/demo_company_a/feed").json()["items"] == []

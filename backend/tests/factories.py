"""Shared synthetic test factories; test modules never import one another."""

import csv
from io import BytesIO

from pypdf import PdfWriter

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Source
from app.services.news import add_publication, ensure_sources

PASSWORD = "Synthetic-Test-Password-2026"


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


def login(client, name="user_a"):
    result = client.post("/auth/login", json={"email": f"{name}@goat.example.org", "password": PASSWORD})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()

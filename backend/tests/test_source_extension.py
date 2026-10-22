import json

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import session_factory, utcnow
from app.models import Event, Source
from app.services.news import collect_news, ensure_sources
from app.services.ranking import rank_event


def test_third_source_is_configured_and_survives_primary_failure(env, monkeypatch):
    path = env / "sources.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "reserve",
                    "name": "Synthetic reserve",
                    "feed_url": "https://reserve.example.org/rss",
                    "allowed_hosts": ["reserve.example.org"],
                }
            ]
        )
    )
    monkeypatch.setenv("NEWS_SOURCES_CONFIG", str(path))
    get_settings.cache_clear()

    def handler(request):
        if request.url.host != "reserve.example.org":
            return httpx.Response(503)
        return httpx.Response(
            200,
            content=b'<rss version="2.0"><channel><title>Reserve</title><item>'
            b"<title>New industry event</title><link>https://reserve.example.org/news/1</link>"
            b"<description>Synthetic source text for testing a configurable reserve without downloading articles. "
            b"This publication is synthetic and contains no real personal information.</description>"
            b"</item></channel></rss>",
        )

    with (
        session_factory()() as db,
        db.begin(),
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
    ):
        result = collect_news(db, client)
        assert result["cbr"]["ok"] is False and result["interfax"]["ok"] is False
        assert result["reserve"]["added"] == 1
        assert db.get(Source, "reserve").last_error is None
        assert collect_news(db, client)["reserve"]["added"] == 0
        assert len(list(db.scalars(select(Event)))) == 1


@pytest.mark.parametrize(
    "items",
    [
        [
            {
                "id": "../bad",
                "name": "Invalid",
                "feed_url": "https://safe.test/rss",
                "allowed_hosts": ["safe.test"],
            }
        ],
        [
            {
                "id": "bad",
                "name": "Invalid",
                "feed_url": "https://other.test/rss",
                "allowed_hosts": ["safe.test"],
            }
        ],
    ],
)
def test_source_config_rejects_unapproved_hosts(env, monkeypatch, items):
    path = env / "invalid.json"
    path.write_text(json.dumps(items))
    monkeypatch.setenv("NEWS_SOURCES_CONFIG", str(path))
    get_settings.cache_clear()
    with session_factory()() as db, pytest.raises(ValueError):
        ensure_sources(db)


def test_new_industry_is_data_not_a_ranker_branch():
    context = {
        "features": {"MAINOKVED_CODE": {"quality": "confirmed", "value": "62.01"}},
        "related_companies": [],
        "payment_links": {"incoming": [], "outgoing": []},
    }
    score, reasons = rank_event(context, {}, {"topics": {"industry": ["62.01"]}}, utcnow())
    assert score == 4 and reasons[0]["event_topic"] == "62.01"

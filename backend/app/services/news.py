import hashlib
import re
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import utcnow
from app.models import Event, Evidence, News, Source, uid

DEFAULT_SOURCES = [
    {
        "id": "cbr",
        "name": "Банк России",
        "feed_url": "https://www.cbr.ru/rss/RssPress",
        "allowed_hosts": ["www.cbr.ru", "cbr.ru"],
    },
    {
        "id": "interfax",
        "name": "Интерфакс",
        "feed_url": "https://www.interfax.ru/rss",
        "allowed_hosts": ["www.interfax.ru", "interfax.ru"],
    },
]


def ensure_sources(db):
    for source in DEFAULT_SOURCES:
        existing = db.get(Source, source["id"])
        if not existing:
            db.add(Source(**source))
        else:
            existing.feed_url = source["feed_url"]
            existing.allowed_hosts = source["allowed_hosts"]
    db.flush()


def normalize_url(url: str, allowed_hosts: list[str]) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or parts.hostname not in allowed_hosts
        or parts.username
        or parts.password
        or parts.port not in {None, 80, 443}
    ):
        raise ValueError("Source URL outside allowed hosts")
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query)
            if not k.casefold().startswith("utm_") and k not in {"from", "ref"}
        )
    )
    return urlunsplit(("https", parts.hostname, parts.path or "/", query, ""))


def normalize_title(title):
    return " ".join(re.findall(r"\w+", title.casefold()))


def plain_html(value):
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def fetch_limited(client: httpx.Client, url: str, max_bytes=2_000_000) -> bytes:
    # No redirect to unvalidated destinations. A source redirect must be configured explicitly.
    with client.stream("GET", url, follow_redirects=False) as response:
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Unexpected source redirect")
        parts, size = [], 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("Source response too large")
            parts.append(chunk)
        return b"".join(parts)


def add_publication(db: Session, source: Source, item: dict) -> tuple[News | None, bool]:
    url = normalize_url(item["url"], source.allowed_hosts)
    content_hash = hashlib.sha256(item["text"].encode()).hexdigest()
    if db.scalar(
        select(News.id).where(
            or_(News.url == url, ((News.source_id == source.id) & (News.content_hash == content_hash)))
        )
    ):
        return None, False
    title_key = normalize_title(item["title"])
    published = item.get("published_at")
    candidates = []
    if published:
        candidates = db.scalars(
            select(Event).where(
                Event.published_at >= published - timedelta(hours=18),
                Event.published_at <= published + timedelta(hours=18),
            )
        ).all()
    event = next(
        (
            e
            for e in candidates
            if (
                e.normalized_title == title_key
                or (
                    SequenceMatcher(None, e.normalized_title, title_key).ratio() >= 0.96
                    and re.findall(r"\d+", e.normalized_title) == re.findall(r"\d+", title_key)
                )
            )
        ),
        None,
    )
    if not event:
        event = Event(id=uid(), title=item["title"], normalized_title=title_key, published_at=published)
        db.add(event)
        db.flush()
    news = News(
        id=uid(),
        source_id=source.id,
        event_id=event.id,
        url=url,
        title=item["title"],
        text=item["text"],
        content_hash=content_hash,
        published_at=published,
    )
    db.add(news)
    db.flush()
    db.add(
        Evidence(
            id=uid(),
            kind="news",
            source_id=news.id,
            version=content_hash,
            locator={"url": url, "published_at": published.isoformat() if published else None},
            excerpt=item["text"][:4000],
        )
    )
    event.version = hashlib.sha256((event.version + content_hash).encode()).hexdigest()
    event.processing_status = "pending_ai"
    return news, True


def collect_news(db: Session, client=None) -> dict:
    ensure_sources(db)
    own_client = client is None
    client = client or httpx.Client(timeout=25, headers={"User-Agent": "GOAT-hack/0.1 news reader"})
    result = {}
    added_total = 0
    try:
        for source in db.scalars(select(Source).order_by(Source.id)):
            if added_total >= get_settings().news_max_new_publications:
                break
            count, errors = 0, 0
            try:
                raw = fetch_limited(client, normalize_url(source.feed_url, source.allowed_hosts))
                feed = feedparser.parse(raw)
                if not feed.entries:
                    raise ValueError("Feed contains no entries")
                for entry in feed.entries[:50]:
                    try:
                        with db.begin_nested():
                            url = normalize_url(entry.get("link", ""), source.allowed_hosts)
                            if db.scalar(select(News.id).where(News.url == url)):
                                continue
                            content = entry.get("content", [{}])[0].get("value", "") or entry.get(
                                "summary", ""
                            )
                            text_value = plain_html(content)
                            if len(text_value) < 100:
                                page = fetch_limited(client, url).decode("utf-8", errors="replace")
                                soup = BeautifulSoup(page, "html.parser")
                                article = soup.find("article") or soup.find("main")
                                text_value = plain_html(str(article)) if article else text_value
                            if not text_value:
                                raise ValueError("No publication text")
                            parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                            date = datetime(*parsed[:6], tzinfo=UTC) if parsed else None
                            news, added = add_publication(
                                db,
                                source,
                                {
                                    "url": url,
                                    "title": entry["title"],
                                    "text": text_value[:100000],
                                    "published_at": date,
                                },
                            )
                            if added:
                                from app.services.queue import enqueue

                                enqueue(
                                    db,
                                    "summarize",
                                    {"event_id": news.event_id},
                                    dedup_key=f"summarize:{news.event_id}",
                                )
                                count += 1
                                added_total += 1
                                if added_total >= get_settings().news_max_new_publications:
                                    break
                    except (ValueError, KeyError, httpx.HTTPError):
                        errors += 1
                source.last_success_at = utcnow()
                source.last_error = None if errors == 0 else "some_entries_failed"
                result[source.id] = {"added": count, "entry_errors": errors, "ok": True}
            except (ValueError, httpx.HTTPError):
                source.last_error = "source_fetch_failed"
                result[source.id] = {"added": count, "ok": False, "error": source.last_error}
    finally:
        if own_client:
            client.close()
    return result

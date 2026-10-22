"""Backend timings on the full isolated audit DB. AI preparation is explicitly synthetic."""

import argparse
import hashlib
import json
import math
import os
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from app.cli import seed_demo
from app.config import get_settings
from app.db import session_factory, utcnow
from app.main import create_app
from app.models import Event, Evidence, Membership, News, Payment, Source, User
from app.services.clients import demo_candidates
from app.services.jobs import run_one


def summary(samples):
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "p50_ms": round(statistics.median(samples), 3),
        "p95_ms": round(ordered[math.ceil(len(samples) * 0.95) - 1], 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    os.environ["AI_MODULE"] = "tests.fake_feed_ai"
    os.environ["FEED_PREPARE_TOP_K"] = "3"
    os.environ["FEED_CANDIDATE_LIMIT"] = "30"
    get_settings.cache_clear()
    password = "Benchmark-local-password-2026"
    with session_factory()() as db, db.begin():
        if db.bind.url.database != "goat_a18":
            raise SystemExit("Only isolated goat_a18 audit database is allowed")
        seed_demo(db, password)
        company = demo_candidates(db, 1)[0]
        company_id = company.id
        user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
        if not db.scalar(
            select(Membership.id).where(Membership.user_id == user.id, Membership.company_id == company_id)
        ):
            db.add(
                Membership(
                    user_id=user.id,
                    company_id=company_id,
                    status="active",
                    position_text="Director",
                    interests=[],
                )
            )
        if not db.get(Source, "benchmark"):
            db.add(
                Source(
                    id="benchmark",
                    name="Synthetic benchmark",
                    feed_url="https://benchmark.example.org/rss",
                    allowed_hosts=["benchmark.example.org"],
                )
            )
            db.flush()
        payment_rows = db.scalar(select(func.count()).select_from(Payment))
        if not db.get(Event, "benchmark-event-0000"):
            events, news, evidence = [], [], []
            for i in range(3000):
                event_id, news_id = f"benchmark-event-{i:04}", f"benchmark-news-{i:04}"
                content = f"Synthetic benchmark news {i}"
                version = hashlib.sha256(content.encode()).hexdigest()
                published = utcnow() - timedelta(seconds=i)
                events.append(
                    dict(
                        id=event_id,
                        title=content,
                        normalized_title=content.lower(),
                        summary=content,
                        published_at=published,
                        topics={"industry": ["62.01"]},
                        processing_status="done",
                    )
                )
                news.append(
                    dict(
                        id=news_id,
                        event_id=event_id,
                        source_id="benchmark",
                        url=f"https://benchmark.example.org/news/{i}",
                        title=content,
                        text=content,
                        content_hash=version,
                        published_at=published,
                    )
                )
                evidence.append(
                    dict(
                        id=f"benchmark-evidence-{i:04}",
                        kind="news",
                        source_id=news_id,
                        version=version,
                        locator={"url": f"https://benchmark.example.org/news/{i}"},
                        excerpt=content,
                    )
                )
            db.execute(insert(Event), events)
            db.execute(insert(News), news)
            db.execute(insert(Evidence), evidence)
    report = {
        "host": {"os": platform.platform(), "cpu": platform.processor(), "logical_cpus": os.cpu_count()},
        "scope": "in-process HTTP TestClient, PostgreSQL on Docker loopback, one real Client profile, 3000 synthetic events",
        "payment_rows_in_database": payment_rows,
        "candidate_event_window": 2000,
        "shortlist": 30,
        "top_k": 3,
        "model": "synthetic test producer, zero paid calls",
    }
    with TestClient(create_app()) as client:
        response = client.post("/auth/login", json={"email": "user_a@goat.example.org", "password": password})
        assert response.status_code == 200
        path = f"/companies/{company_id}/feed"

        def timed(url):
            start = time.perf_counter()
            result = client.get(url)
            assert result.status_code == 200, result.text[:200]
            return (time.perf_counter() - start) * 1000, result.json()

        cold_http, queued = timed(path + "?contract_version=v2")
        start = time.perf_counter()
        assert run_one()
        report["cold_backend_prepare_ms"] = round((time.perf_counter() - start) * 1000, 3)
        report["cold_get_ms"] = round(cold_http, 3)
        _, ready = timed(path + "?contract_version=v2&snapshot_id=" + queued["snapshot_id"])
        assert sum(item["generation_status"] == "ready" for item in ready["items"]) == 3
        report["v1_sequential"] = summary([timed(path)[0] for _ in range(30)])
        report["v2_warm_sequential"] = summary([timed(path + "?contract_version=v2")[0] for _ in range(30)])
        with ThreadPoolExecutor(max_workers=4) as pool:
            report["v2_warm_concurrency_4"] = summary(
                list(pool.map(lambda _: timed(path + "?contract_version=v2")[0], range(40)))
            )
        report["status"] = ready["generation_status"]
        report["warm_llm_calls"] = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

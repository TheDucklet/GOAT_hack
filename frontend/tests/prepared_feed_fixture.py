"""Seed/mutate only a dedicated R13 synthetic acceptance database."""

import json
import sys

from sqlalchemy import select

sys.path.insert(0, "/srv/backend")

from app.cli import seed_demo
from app.db import session_factory, utcnow
from app.models import Company, Event, Evidence, Membership, News, Source, User

with session_factory()() as db, db.begin():
    if db.bind.url.database != "goat_r13":
        raise SystemExit("Only dedicated goat_r13 is allowed")
    if sys.argv[1] == "seed":
        if db.scalar(select(User.id).limit(1)):
            raise SystemExit(
                "Use a fresh R13 project; existing user data is never replaced"
            )
        seed_demo(db, json.load(sys.stdin)["password"])
        company = db.get(Company, "demo_company_a")
        company.features = {
            **company.features,
            "confirmed_debt_terms": {
                "value": "Учебный действующий кредит с плавающей ставкой",
                "quality": "confirmed",
                "provenance": {"synthetic": True},
            },
        }
        company = db.get(Company, "demo_company_b")
        company.features = {
            **company.features,
            "CL_PRODUCT_RKO_MARK": {
                "value": "1",
                "quality": "confirmed",
                "provenance": {"synthetic": True},
            },
        }
        user = db.scalar(select(User).where(User.email == "user_a@goat.example.org"))
        db.add(
            Membership(
                user_id=user.id,
                company_id="demo_company_b",
                status="active",
                position_text="Финансовый директор",
                interests=[],
            )
        )
        source = Source(
            id="r13-source",
            name="Учебный источник",
            feed_url="https://example.org/feed",
            allowed_hosts=["example.org"],
        )
        db.add(source)
        db.flush()
        for name, title in [
            ("main", "Учебное изменение ставки"),
            ("deferred", "Учебный отказ подготовки"),
        ]:
            event_id = "r13-0-main" if name == "main" else "r13-" + name
            db.add(
                Event(
                    id=event_id,
                    title=title,
                    normalized_title=title.lower(),
                    summary="Исходная учебная новость, не персональный вывод.",
                    topics={"industry": ["25.61"]},
                    published_at=utcnow(),
                    processing_status="done",
                )
            )
            db.flush()
            db.add(
                News(
                    id="r13-news-" + name,
                    source_id=source.id,
                    event_id=event_id,
                    title=title,
                    text="Синтетика: ставка для пересматриваемого договора повышается на один процентный пункт.",
                    url="https://example.org/r13/" + name,
                    content_hash="r13-" + name,
                    published_at=utcnow(),
                )
            )
            db.flush()
            db.add(
                Evidence(
                    id="r13-evidence-" + name,
                    kind="news",
                    source_id="r13-news-" + name,
                    version="r13-" + name,
                    locator={"url": "https://example.org/r13/" + name},
                    excerpt="Синтетика: ставка для пересматриваемого договора повышается на один процентный пункт.",
                )
            )
    elif sys.argv[1] == "stale":
        db.get(Company, "demo_company_a").profile_version = "r13-updated-profile"
    else:
        raise SystemExit("Unknown operation")
print(json.dumps({"result": "PASS", "mode": "synthetic"}))

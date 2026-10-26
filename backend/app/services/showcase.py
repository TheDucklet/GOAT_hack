"""Explicit, idempotent submission fixtures; never called by application startup."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.data_semantics import DATA_SEMANTICS_VERSION, normalize_feature
from app.models import Company, Event, Membership, News, Source, User
from app.services.news import add_publication, ensure_sources
from app.services.queue import enqueue
from app.services.sessions import hasher

FIXTURE = Path(__file__).parents[1] / "demo" / "showcase.json"


def seed_showcase(db, password: str, *, phase: str = "baseline", enqueue_ai: bool = False):
    if len(password) < 10:
        raise ValueError("Set DEMO_PASSWORD to at least 10 characters")
    if phase not in {"baseline", "unseen"}:
        raise ValueError("Unknown showcase phase")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    version = fixture["version"]
    accounts = []
    for item in fixture["companies"]:
        company = db.get(Company, item["id"])
        if company and company.profile_version != version:
            raise ValueError("Showcase company ID is already used by another dataset")
        if not company:
            values = item["features"]
            db.add(Company(
                id=item["id"], name=item["name"], profile_version=version,
                data_semantics_version=DATA_SEMANTICS_VERSION,
                identity_quality="confirmed", client_type="Client",
                features={field: {
                    **normalize_feature(field, [(1, values)], version),
                    "provenance": {"file": version, "field": field, "synthetic": True},
                } for field in values},
                unknowns=item["unknowns"],
            ))
    db.flush()
    for item in fixture["companies"]:
        for role in fixture["roles"]:
            email = f"{item['id']}.{role['id']}@goat.example.org"
            user = db.scalar(select(User).where(User.email == email))
            if user:
                membership = db.scalar(select(Membership).where(
                    Membership.user_id == user.id, Membership.company_id == item["id"],
                ))
                if (not membership or membership.status != "active"
                        or user.status != "active" or user.system_role != "user"):
                    raise ValueError("Existing showcase account was changed; refusing to grant access")
            else:
                user = User(email=email, password_hash=hasher.hash(password))
                db.add(user)
                db.flush()
                db.add(Membership(
                    user_id=user.id, company_id=item["id"], status="active",
                    position_text=role["position"], interests=role["interests"],
                ))
            accounts.append({"email": email, "company_id": item["id"], "position": role["position"]})
    admin = db.scalar(select(User).where(User.email == "admin@goat.example.org"))
    if admin and (admin.system_role != "admin" or admin.status != "active"):
        raise ValueError("Existing admin address is not an active admin; refusing to elevate it")
    if not admin:
        db.add(User(email="admin@goat.example.org", password_hash=hasher.hash(password), system_role="admin"))
    ensure_sources(db)
    source = db.get(Source, "cbr")
    events = []
    for item in fixture["events"]:
        if item["phase"] != phase:
            continue
        news = db.scalar(select(News).where(News.url == item["url"]))
        if news and news.content_hash != hashlib.sha256(item["text"].encode()).hexdigest():
            raise ValueError("Publication already has different content; use a separate demo database")
        if not news:
            news, _ = add_publication(db, source, {
                **item, "published_at": datetime.fromisoformat(item["published_at"]),
            })
        event = db.get(Event, news.event_id)
        job = None
        if enqueue_ai and event.processing_status != "done":
            job = enqueue(db, "summarize", {"event_id": event.id}, dedup_key=f"summarize:{event.id}")
        events.append({"event_id": event.id, "phase": phase, "job_id": job.id if job else None})
    return {"dataset": version, "synthetic_companies": True, "accounts": accounts,
            "admin_email": "admin@goat.example.org", "events": events,
            "password_policy": "DEMO_PASSWORD for new accounts only; existing passwords are retained"}

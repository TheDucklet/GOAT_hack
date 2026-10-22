"""Private interactions and content-free product telemetry. No outbound action adapters."""

import hashlib
import json
from datetime import timedelta

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import utcnow
from app.errors import AppError
from app.models import DemoAction, Event, FeedDismissal, Insight, Membership, ProductEvent
from app.services.access import company_access, owned
from app.services.events import event_version


def target(db, user, company_id, event_id, insight_id=None):
    membership = company_access(db, user, company_id)
    db.scalar(select(Membership).where(Membership.id == membership.id).with_for_update())
    event = db.get(Event, event_id)
    if not event:
        raise AppError(404, "not_found", "Событие не найдено")
    insight = owned(db, Insight, insight_id, user) if insight_id else None
    if insight and (insight.company_id != company_id or insight.event_id != event_id):
        raise AppError(403, "forbidden", "Карточка не относится к выбранному событию и компании")
    return event, insight


def record_event(db, user, company_id, event, insight, kind, session_hash, user_agent="", identity=None):
    settings = get_settings()
    if user.system_role == "admin":
        reason = "admin"
    elif any(word in user_agent.lower() for word in ("bot", "crawler", "spider", "headless")):
        reason = "bot"
    elif (
        settings.environment == "test"
        or user.email in settings.product_test_emails
        or user.email.endswith("@goat.example.org")
    ):
        reason = "test"
    else:
        reason = None
    version = insight.cache_key if insight else event_version(event)
    key = hashlib.sha256(
        json.dumps(
            [user.id, company_id, event.id, version, kind, None if identity else session_hash, identity]
        ).encode()
    ).hexdigest()
    previous = db.scalar(select(ProductEvent).where(ProductEvent.dedup_key == key))
    if previous:
        return previous, False
    obj = ProductEvent(
        user_id=user.id,
        company_id=company_id,
        event_id=event.id,
        insight_id=insight.id if insight else None,
        event_type=kind,
        session_hash=session_hash,
        version=version,
        versions=insight.versions if insight else {"event": version},
        dedup_key=key,
        excluded_reason=reason,
    )
    db.add(obj)
    db.flush()
    return obj, True


def set_dismissal(db, user, company_id, body):
    event, insight = target(db, user, company_id, body.event_id, body.insight_id)
    version = insight.cache_key if insight else "*"
    statement = select(FeedDismissal).where(
        FeedDismissal.user_id == user.id,
        FeedDismissal.company_id == company_id,
        FeedDismissal.event_id == event.id,
        FeedDismissal.version == version,
    )
    previous = db.scalar(statement)
    if body.hidden and not previous:
        db.add(FeedDismissal(user_id=user.id, company_id=company_id, event_id=event.id, version=version))
    elif not body.hidden and previous:
        db.delete(previous)
    db.flush()
    return event, insight, {"event_id": event.id, "version": version, "hidden": body.hidden}


def demo_action(db, user, company_id, body):
    event, insight = target(db, user, company_id, body.event_id, body.insight_id)
    previous = db.scalar(
        select(DemoAction).where(
            DemoAction.user_id == user.id,
            DemoAction.company_id == company_id,
            DemoAction.idempotency_key == body.idempotency_key,
        )
    )
    if previous:
        if (previous.event_id, previous.insight_id, previous.action_type) != (
            body.event_id,
            body.insight_id,
            body.action_type,
        ):
            raise AppError(409, "idempotency_conflict", "Ключ уже использован для другого действия")
        return event, insight, previous
    obj = DemoAction(user_id=user.id, company_id=company_id, **body.model_dump())
    db.add(obj)
    db.flush()
    return event, insight, obj


def purge_events(db):
    cutoff = utcnow() - timedelta(days=get_settings().product_event_retention_days)
    return db.execute(delete(ProductEvent).where(ProductEvent.created_at < cutoff)).rowcount


def product_metrics(db):
    cutoff = utcnow() - timedelta(days=get_settings().product_event_retention_days)
    rows = list(
        db.execute(
            select(ProductEvent.event_type, func.count())
            .where(ProductEvent.excluded_reason.is_(None), ProductEvent.created_at >= cutoff)
            .group_by(ProductEvent.event_type)
        )
    )
    counts = {name: 0 for name in ("impression", "open", "chat", "action", "hide", "restore", "feedback")}
    counts.update(dict(rows))
    impressions, opens = counts["impression"], counts["open"]
    return {
        "counts": counts,
        "open_rate": opens / impressions if impressions else None,
        "action_rate": counts["action"] / opens if opens else None,
        "hide_rate": counts["hide"] / impressions if impressions else None,
        "retention_days": get_settings().product_event_retention_days,
        "zero_denominator": "N/A",
        "scope": "nonexcluded session-version events",
    }

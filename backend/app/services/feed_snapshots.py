"""HTTP-side snapshot production and authorized reads. Never invokes generation."""

import hashlib
import json
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import as_utc, utcnow
from app.errors import AppError
from app.models import Event, FeedDismissal, FeedSnapshot, Insight, Job, Membership, News
from app.schemas import InsightOut
from app.services.access import company_access
from app.services.clients import company_context
from app.services.events import event_version
from app.services.feed_ranking import RANKING_VERSION, runtime_result, score_preview
from app.services.insights import company_versions, insight_key, insight_versions
from app.services.queue import enqueue
from app.services.ranking import rank_event

MOSCOW = ZoneInfo("Europe/Moscow")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def local_day(now):
    return as_utc(now).astimezone(MOSCOW).date()


def candidate_versions(common, event):
    return {**common, "event": event_version(event)}


def exclusions(db, user_id, company_id):
    return set(
        db.execute(
            select(FeedDismissal.event_id, FeedDismissal.version).where(
                FeedDismissal.user_id == user_id, FeedDismissal.company_id == company_id
            )
        ).all()
    )


def is_excluded(hidden, event_id, cache_key):
    return (event_id, "*") in hidden or (event_id, cache_key) in hidden


def candidates(db, user, company_id, common, now):
    settings = get_settings()
    membership = company_access(db, user, company_id)
    context = company_context(db, company_id)
    focus = (
        membership.user_focus
        if membership.focus_input_hash == common["focus"]
        else {"topics": membership.interests}
    )
    events = {
        event.id: event
        for event in db.scalars(
            select(Event)
            .where(Event.visible.is_(True))
            .order_by(Event.published_at.desc().nullslast(), Event.id)
            .limit(2000)
        )
    }
    # Carry forward recent saved active conclusions even when their source is outside the news window.
    saved = list(
        db.scalars(
            select(Insight)
            .where(Insight.user_id == user.id, Insight.company_id == company_id)
            .order_by(Insight.created_at.desc(), Insight.id)
            .limit(200)
        )
    )
    old_ids = {
        item.event_id
        for item in saved
        if item.result.get("schema_version") == "v2"
        and runtime_result(item.result, local_day(now))["relevance_status"] in {"active", "review_required"}
    }
    for event in db.scalars(select(Event).where(Event.id.in_(old_ids), Event.visible.is_(True))):
        events[event.id] = event
    keys = {
        item.id: insight_key(user.id, company_id, item.id, candidate_versions(common, item))
        for item in events.values()
    }
    cached = {
        item.cache_key: item
        for item in db.scalars(select(Insight).where(Insight.cache_key.in_(keys.values())))
    }
    hidden = exclusions(db, user.id, company_id)
    sources = {}
    for publication in db.scalars(select(News).where(News.event_id.in_(events))):
        sources.setdefault(publication.event_id, []).append(
            dict(id=publication.source_id, url=publication.url)
        )
    ranking_time = datetime.combine(local_day(now), time.min, tzinfo=MOSCOW)
    result = []
    for event in events.values():
        key = keys[event.id]
        if is_excluded(hidden, event.id, key):
            continue
        score, reasons = rank_event(
            context, focus, dict(topics=event.topics, published_at=event.published_at), ranking_time
        )
        previous = cached.get(key)
        value = previous.result if previous and previous.result.get("schema_version") == "v2" else None
        selection_score, _ = score_preview(score, reasons, value, local_day(now))
        result.append(
            dict(
                event_id=event.id,
                title=event.title,
                summary=event.summary,
                published_at=as_utc(event.published_at).isoformat() if event.published_at else None,
                status=event.processing_status,
                sources=sources.get(event.id, []),
                cache_key=key,
                versions=candidate_versions(common, event),
                candidate_score=score,
                candidate_reasons=reasons,
                selection_score=selection_score,
            )
        )
    result.sort(key=lambda item: (-item["selection_score"], item["event_id"]))
    return result[: settings.feed_candidate_limit]


def request_snapshot(db, user, company_id):
    membership = company_access(db, user, company_id)
    # Serialize producers for this profile; unique input_key is the final cross-process safeguard.
    db.scalar(
        select(Membership)
        .where(Membership.id == membership.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    common = company_versions(db, user, company_id)
    now = utcnow()
    selected = candidates(db, user, company_id, common, now)
    settings = get_settings()
    versions = dict(
        inputs=common,
        events={item["event_id"]: item["versions"]["event"] for item in selected},
        ranking=RANKING_VERSION,
        top_k=settings.feed_prepare_top_k,
        candidate_limit=settings.feed_candidate_limit,
        weights=settings.ranking_weights,
        as_of=local_day(now).isoformat(),
    )
    key = digest([user.id, company_id, versions])
    previous = db.scalar(select(FeedSnapshot).where(FeedSnapshot.input_key == key))
    if previous:
        return previous
    try:
        with db.begin_nested():
            snapshot = FeedSnapshot(
                user_id=user.id,
                company_id=company_id,
                input_key=key,
                versions=versions,
                candidates=selected,
                created_at=now,
            )
            db.add(snapshot)
            db.flush()
            if selected:
                job = enqueue(
                    db,
                    "feed_prepare",
                    {"snapshot_id": snapshot.id},
                    user.id,
                    company_id,
                    dedup_key=f"feed:{key}",
                )
                snapshot.job_id = job.id
            else:
                snapshot.status, snapshot.ready_at = "ready", now
        return snapshot
    except IntegrityError:
        winner = db.scalar(select(FeedSnapshot).where(FeedSnapshot.input_key == key))
        if winner is None:
            raise
        return winner


def owned_snapshot(db, user, company_id, snapshot_id):
    company_access(db, user, company_id)
    snapshot = db.get(FeedSnapshot, snapshot_id)
    if not snapshot:
        raise AppError(404, "not_found", "Снимок ленты не найден")
    if snapshot.user_id != user.id or snapshot.company_id != company_id:
        raise AppError(403, "forbidden", "Снимок ленты недоступен")
    return snapshot


def changed_inputs(snapshot, common):
    old = snapshot.versions["inputs"]
    return sorted(key for key in set(old) | set(common) if old.get(key) != common.get(key))


def present_insight(db, user, insight, now=None, common=None):
    now = now or utcnow()
    if common is None:
        current, _ = insight_versions(db, user, insight.company_id, insight.event_id)
    else:
        event = db.get(Event, insight.event_id)
        if not event or not event.visible:
            raise AppError(404, "not_found", "Событие недоступно")
        current = candidate_versions(common, event)
    changed = sorted(
        key for key in set(current) | set(insight.versions) if current.get(key) != insight.versions.get(key)
    )
    return InsightOut(
        id=insight.id,
        company_id=insight.company_id,
        event_id=insight.event_id,
        versions=insight.versions,
        result=runtime_result(insight.result, local_day(now)),
        stale=bool(changed),
        stale_reasons=changed,
        evaluated_at=now,
    )


def read_snapshot(db, user, snapshot, limit, offset):
    company_access(db, user, snapshot.company_id)
    now = utcnow()
    common = company_versions(db, user, snapshot.company_id)
    changes = changed_inputs(snapshot, common)
    job = db.get(Job, snapshot.job_id) if snapshot.job_id else None
    state = snapshot.status
    error = snapshot.error
    if state in {"queued", "running"} and job:
        state = {"queued": "queued", "running": "running", "failed": "failed"}.get(job.status, state)
        error = job.error or error
    rows = snapshot.items
    total = len(rows)
    page = rows[offset : offset + limit]
    hidden = exclusions(db, user.id, snapshot.company_id)
    event_ids = list(snapshot.versions["events"])
    events = {item.id: item for item in db.scalars(select(Event).where(Event.id.in_(event_ids)))}
    event_changes = [
        f"event:{event_id}"
        for event_id, version in snapshot.versions["events"].items()
        if event_id not in events or (events[event_id].visible and event_version(events[event_id]) != version)
    ]
    insights = {
        item.id: item
        for item in db.scalars(
            select(Insight).where(
                Insight.id.in_([row["insight_id"] for row in page if row.get("insight_id")])
            )
        )
    }
    output = []
    for row in page:
        event = events.get(row["event_id"])
        if not event or not event.visible or is_excluded(hidden, event.id, row["cache_key"]):
            continue
        item = {
            name: value
            for name, value in row.items()
            if name not in {"cache_key", "candidate_score", "candidate_reasons", "selection_score"}
        }
        stale = bool(changes) or event_version(event) != row["versions"]["event"]
        if stale:
            item.update(
                generation_status="stale",
                personalized_summary=None,
                insight_id=None,
                impact_level="undetermined",
                relevance_status="undetermined",
            )
        elif row.get("insight_id"):
            insight = insights.get(row["insight_id"])
            if (
                not insight
                or insight.user_id != user.id
                or insight.company_id != snapshot.company_id
                or insight.event_id != event.id
            ):
                raise AppError(403, "forbidden", "Карточка снимка недоступна")
            result = runtime_result(insight.result, local_day(now))
            item.update(
                personalized_summary=result.get("personalized_summary"),
                impact_level=result.get("impact_level", "undetermined"),
                relevance_status=result.get("relevance_status", "undetermined"),
                mechanism=result.get("mechanism", []),
                impact_reason=result.get("impact_reason"),
                time_horizon=result.get("time_horizon"),
                relevance_reason=result.get("relevance_reason"),
                valid_from=result.get("valid_from"),
                valid_until=result.get("valid_until"),
                review_after=result.get("review_after"),
                unknowns=result.get("unknowns", []),
            )
        output.append(item)
    # Offsets address frozen slots, not a re-packed filtered list. Hiding cannot duplicate next-page rows.
    return dict(
        schema_version="v2",
        snapshot_id=snapshot.id,
        generation_status="stale" if changes or event_changes else state,
        versions=snapshot.versions,
        stale=bool(changes or event_changes),
        stale_reasons=changes + event_changes,
        ranking_version=snapshot.versions["ranking"],
        ranking_as_of=as_utc(snapshot.created_at),
        ready_at=as_utc(snapshot.ready_at) if snapshot.ready_at else None,
        job_id=snapshot.job_id,
        error=error,
        items=output,
        total=total,
        limit=limit,
        offset=offset,
        next_offset=offset + limit if offset + limit < total else None,
    )

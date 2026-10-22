"""Bounded feed generation on the existing queue. HTTP reads never call this."""

from types import SimpleNamespace

from sqlalchemy import select

from app.db import as_utc, utcnow
from app.errors import AppError
from app.integrations.ai import AIError
from app.models import Event, FeedSnapshot, Insight, User
from app.services.access import company_access
from app.services.clients import company_context
from app.services.events import event_version
from app.services.feed_ranking import score_preview
from app.services.feed_snapshots import changed_inputs, exclusions, is_excluded, local_day
from app.services.insights import company_versions
from app.services.job_handlers.analysis import insight_job, user_context
from app.services.ranking import rank_event


def prepare_feed_job(db, job):
    user = db.get(User, job.user_id, with_for_update=True, populate_existing=True)
    if not user or user.status != "active":
        raise AppError(403, "forbidden", "Доступ отозван")
    company_access(db, user, job.company_id)
    snapshot = db.get(FeedSnapshot, job.payload["snapshot_id"], with_for_update=True)
    if not snapshot or snapshot.user_id != user.id or snapshot.company_id != job.company_id:
        raise AppError(403, "forbidden", "Снимок ленты недоступен")
    if snapshot.status not in {"queued", "running"}:
        return {"snapshot_id": snapshot.id, "generation_status": snapshot.status}
    common = company_versions(db, user, job.company_id)
    if changed_inputs(snapshot, common):
        snapshot.status = "stale"
        return {"snapshot_id": snapshot.id, "generation_status": "stale"}
    snapshot.status = "running"
    rows, attempted = [], 0
    cutoff = None
    hidden = exclusions(db, user.id, job.company_id)
    selected = [dict(candidate) for candidate in snapshot.candidates]
    cached = {
        item.cache_key: item
        for item in db.scalars(
            select(Insight).where(Insight.cache_key.in_([candidate["cache_key"] for candidate in selected]))
        )
    }
    if any(candidate["cache_key"] not in cached for candidate in selected):
        try:
            _, _, focus = user_context(db, job)
            context = company_context(db, job.company_id)
            for candidate in selected:
                event = db.get(Event, candidate["event_id"])
                if event and event.visible:
                    score, reasons = rank_event(
                        context,
                        focus,
                        dict(topics=event.topics, published_at=event.published_at),
                        as_utc(snapshot.created_at),
                    )
                    candidate["candidate_score"], candidate["candidate_reasons"] = score, reasons
                    previous = cached.get(candidate["cache_key"])
                    candidate["selection_score"], _ = score_preview(
                        score, reasons, previous.result if previous else None, local_day(snapshot.created_at)
                    )
            selected.sort(key=lambda candidate: (-candidate["selection_score"], candidate["event_id"]))
        except AIError as exc:
            cutoff = exc.code
    for candidate in selected:
        event = db.get(Event, candidate["event_id"], populate_existing=True)
        if not event or not event.visible or is_excluded(hidden, event.id, candidate["cache_key"]):
            continue
        row = {
            **candidate,
            "generation_status": "not_requested",
            "insight_id": None,
            "personalized_summary": None,
            "impact_level": "undetermined",
            "relevance_status": "undetermined",
            "error": None,
        }
        insight = None
        if event_version(event) != candidate["versions"]["event"]:
            row["generation_status"] = "stale"
        else:
            insight = db.scalar(select(Insight).where(Insight.cache_key == candidate["cache_key"]))
            if insight and insight.result.get("schema_version") != "v2":
                insight = None
            if not insight and cutoff:
                row.update(generation_status="deferred", error={"code": cutoff})
            elif not insight and attempted < snapshot.versions["top_k"]:
                attempted += 1
                try:
                    with db.begin_nested():
                        child = SimpleNamespace(
                            id=job.id,
                            user_id=job.user_id,
                            company_id=job.company_id,
                            payload={"event_id": event.id, "expected_cache_key": candidate["cache_key"]},
                        )
                        result = insight_job(db, child)
                        insight = db.get(Insight, result["insight_id"])
                        if insight.result.get("schema_version") != "v2":
                            raise AIError("ai_contract_error", "Для ленты v2 требуется карточка v2")
                except (AIError, AppError) as exc:
                    insight = None
                    deferred = exc.code in {
                        "budget_exhausted",
                        "provider_unavailable",
                        "rate_limited",
                        "timeout",
                    }
                    row.update(
                        generation_status="deferred" if deferred else "failed", error={"code": exc.code}
                    )
                    if deferred or exc.code == "ai_unavailable":
                        cutoff = exc.code
        value = insight.result if insight else None
        score, reasons = score_preview(
            candidate["candidate_score"], candidate["candidate_reasons"], value, local_day(utcnow())
        )
        row.update(rank_score=score, relevance_reasons=reasons)
        if insight:
            row.update(
                generation_status="ready",
                insight_id=insight.id,
                personalized_summary=value["personalized_summary"],
                impact_level=value["impact_level"],
                relevance_status=value["relevance_status"],
            )
        rows.append(row)
    # Check access and all shared versions again before publishing a completed snapshot.
    db.refresh(user)
    if user.status != "active":
        raise AppError(403, "forbidden", "Доступ отозван")
    company_access(db, user, job.company_id)
    if changed_inputs(snapshot, company_versions(db, user, job.company_id)):
        snapshot.status = "stale"
        return {"snapshot_id": snapshot.id, "generation_status": "stale"}
    ready = sum(row["generation_status"] == "ready" for row in rows)
    failed = any(row["generation_status"] == "failed" for row in rows)
    deferred = any(row["generation_status"] == "deferred" for row in rows)
    snapshot.status = (
        ("partial" if failed or deferred else "ready")
        if ready
        else ("deferred" if deferred else "failed" if failed else "ready")
    )
    rows.sort(key=lambda row: (row["generation_status"] != "ready", -row["rank_score"], row["event_id"]))
    snapshot.items, snapshot.ready_at = rows, utcnow()
    snapshot.error = {"code": cutoff} if cutoff else None
    return {
        "snapshot_id": snapshot.id,
        "generation_status": snapshot.status,
        "attempted": attempted,
        "ready": ready,
    }

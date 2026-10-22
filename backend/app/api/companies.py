from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, utcnow
from app.models import Company, Event, Membership, News, User
from app.schemas import CompanyContext, CompanyContextV2, CompanyOut, FeedOut, FeedSnapshotOut
from app.security import current_user
from app.services.access import company_access
from app.services.clients import company_context
from app.services.feed_snapshots import (
    candidate_versions,
    exclusions,
    is_excluded,
    owned_snapshot,
    read_snapshot,
    request_snapshot,
)
from app.services.focus import focus_hash
from app.services.insights import company_versions, insight_key
from app.services.queue import enqueue
from app.services.ranking import rank_event

router = APIRouter(tags=["companies"])


@router.get("/companies", response_model=list[CompanyOut])
def companies(user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")):
    return list(
        db.scalars(
            select(Company)
            .join(Membership)
            .where(Membership.user_id == user.id, Membership.status == "active")
            .order_by(Company.id)
        )
    )


@router.get("/companies/{company_id}/context", response_model=CompanyContextV2 | CompanyContext)
def context(
    company_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    company_access(db, user, company_id)
    return company_context(db, company_id)


@router.get("/companies/{company_id}/feed", response_model=FeedOut | FeedSnapshotOut)
def feed(
    company_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    contract_version: Literal["v1", "v2"] = "v1",
    snapshot_id: str | None = Query(None, min_length=1, max_length=36),
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    if contract_version == "v2":
        snapshot = (
            owned_snapshot(db, user, company_id, snapshot_id)
            if snapshot_id
            else request_snapshot(db, user, company_id)
        )
        return read_snapshot(db, user, snapshot, limit, offset)
    membership = company_access(db, user, company_id)
    ctx = company_context(db, company_id)
    focus = membership.user_focus if membership.focus_input_hash == focus_hash(membership) else {}
    if not focus and get_settings().ai_module:
        enqueue(
            db,
            "focus",
            {"membership_id": membership.id},
            user.id,
            company_id,
            dedup_key=f"focus:{membership.id}",
        )
    items = []
    events = list(
        db.scalars(
            select(Event)
            .where(Event.visible.is_(True))
            .order_by(Event.published_at.desc().nullslast(), Event.id)
            .limit(2000)
        )
    )
    publications = list(db.scalars(select(News).where(News.event_id.in_([e.id for e in events]))))
    sources = {}
    for publication in publications:
        sources.setdefault(publication.event_id, []).append(
            {"id": publication.source_id, "url": publication.url}
        )
    now = utcnow()
    hidden = exclusions(db, user.id, company_id)
    common = company_versions(db, user, company_id) if hidden else None
    for event in events:
        if hidden and is_excluded(
            hidden, event.id, insight_key(user.id, company_id, event.id, candidate_versions(common, event))
        ):
            continue
        score, reasons = rank_event(
            ctx, focus, {"topics": event.topics, "published_at": event.published_at}, now
        )
        items.append(
            {
                "event_id": event.id,
                "title": event.title,
                "summary": event.summary,
                "published_at": event.published_at,
                "rank_score": score,
                "relevance_reasons": reasons,
                "status": event.processing_status,
                "sources": sources.get(event.id, []),
            }
        )
    items.sort(key=lambda item: (-item["rank_score"], item["event_id"]))
    return {"items": items[offset : offset + limit], "total": len(items), "offset": offset, "limit": limit}

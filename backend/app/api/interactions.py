from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import FeedDismissal, User
from app.schemas import (
    DemoActionIn,
    DemoActionOut,
    DismissalIn,
    DismissalOut,
    ProductEventIn,
    ProductEventOut,
)
from app.security import admin_user, current_user
from app.services.access import company_access
from app.services.interactions import demo_action, product_metrics, record_event, set_dismissal, target

router = APIRouter(tags=["interactions"])


@router.get("/companies/{company_id}/dismissals", response_model=list[DismissalOut])
def dismissals(
    company_id: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    company_access(db, user, company_id)
    rows = db.scalars(
        select(FeedDismissal)
        .where(FeedDismissal.user_id == user.id, FeedDismissal.company_id == company_id)
        .order_by(FeedDismissal.id)
        .offset(offset)
        .limit(limit)
    )
    return [{"event_id": row.event_id, "version": row.version, "hidden": True} for row in rows]


def record(db, user, company_id, event, insight, kind, request, identity=None):
    return record_event(
        db,
        user,
        company_id,
        event,
        insight,
        kind,
        request.state.login_session.token_hash,
        request.headers.get("user-agent", ""),
        identity,
    )


@router.post("/companies/{company_id}/dismissals", response_model=DismissalOut)
def dismissal(
    company_id: str,
    body: DismissalIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    event, insight, result = set_dismissal(db, user, company_id, body)
    record(db, user, company_id, event, insight, "hide" if body.hidden else "restore", request)
    return result


@router.post("/companies/{company_id}/demo-actions", response_model=DemoActionOut)
def action(
    company_id: str,
    body: DemoActionIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    event, insight, result = demo_action(db, user, company_id, body)
    record(db, user, company_id, event, insight, "action", request, result.id)
    return result


@router.post("/companies/{company_id}/product-events", response_model=ProductEventOut)
def product_event(
    company_id: str,
    body: ProductEventIn,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    event, insight = target(db, user, company_id, body.event_id, body.insight_id)
    if not event.visible:
        raise AppError(404, "not_found", "Событие недоступно")
    obj, created = record(db, user, company_id, event, insight, body.event_type, request)
    return {
        "id": obj.id,
        "event_type": obj.event_type,
        "recorded": created,
        "excluded_reason": obj.excluded_reason,
    }


@router.get("/admin/product-metrics", response_model=dict)
def metrics(user: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")):
    return product_metrics(db)

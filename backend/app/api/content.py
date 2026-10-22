from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import BankDocument, Chat, Evidence, Feedback, Insight, Job, Message, News, User
from app.schemas import (
    ChatIn,
    ChatOut,
    EventIn,
    EvidenceOut,
    FeedbackIn,
    FeedbackOut,
    InsightOut,
    JobOut,
    MessageIn,
    MessageOut,
)
from app.security import current_user
from app.services.access import company_access, owned
from app.services.events import event_context
from app.services.feed_snapshots import present_insight
from app.services.insights import insight_versions
from app.services.queue import enqueue

router = APIRouter(tags=["analytics"])


@router.post(
    "/companies/{company_id}/insights",
    response_model=InsightOut,
    responses={202: {"model": JobOut, "description": "Анализ поставлен в очередь"}},
)
def create_insight(
    company_id: str,
    body: EventIn,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    company_access(db, user, company_id)
    versions, key = insight_versions(db, user, company_id, body.event_id)
    previous = db.scalar(select(Insight).where(Insight.cache_key == key))
    if previous:
        return present_insight(db, user, previous)
    from fastapi.responses import JSONResponse

    job = enqueue(db, "insight", {"event_id": body.event_id}, user.id, company_id, f"insight:{key}")
    return JSONResponse(status_code=202, content=JobOut.model_validate(job).model_dump(mode="json"))


@router.get("/insights/{insight_id}", response_model=InsightOut)
def get_insight(
    insight_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    return present_insight(db, user, owned(db, Insight, insight_id, user))


@router.post("/chats", response_model=ChatOut, status_code=201)
def create_chat(
    body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    company_access(db, user, body.company_id)
    event_context(db, body.event_id)
    chat = Chat(user_id=user.id, **body.model_dump())
    db.add(chat)
    db.flush()
    return chat


@router.post("/chats/{chat_id}/messages", response_model=JobOut, status_code=202)
def send_message(
    chat_id: str,
    body: MessageIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    chat = owned(db, Chat, chat_id, user)
    db.scalar(select(Chat).where(Chat.id == chat.id).with_for_update())
    active = db.scalar(select(Job.id).where(Job.dedup_key == f"chat:{chat.id}"))
    if active:
        raise AppError(409, "chat_busy", "Предыдущий вопрос ещё обрабатывается")
    sequence = (db.scalar(select(func.max(Message.sequence)).where(Message.chat_id == chat.id)) or 0) + 1
    message = Message(chat_id=chat.id, role="user", text=body.text, sequence=sequence)
    db.add(message)
    db.flush()
    return enqueue(
        db,
        "chat",
        {"chat_id": chat.id, "event_id": chat.event_id, "message_id": message.id},
        user.id,
        chat.company_id,
        f"chat:{chat.id}",
    )


@router.get("/chats/{chat_id}/messages", response_model=list[MessageOut])
def messages(
    chat_id: str,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db, scope="function"),
):
    owned(db, Chat, chat_id, user)
    return list(
        db.scalars(
            select(Message)
            .where(Message.chat_id == chat_id)
            .order_by(Message.sequence)
            .offset(offset)
            .limit(limit)
        )
    )


def accessible_source(db, source_id, user):
    obj = db.get(Evidence, source_id)
    if not obj:
        raise AppError(404, "not_found", "Источник не найден")
    if obj.company_id:
        company_access(db, user, obj.company_id)
    if obj.kind == "company" and (not obj.company_id):
        raise AppError(403, "forbidden", "Клиентский источник без прав доступа")
    if obj.kind == "news":
        news = db.get(News, obj.source_id)
        if not news:
            raise AppError(404, "not_found", "Публикация не найдена")
        if user.system_role != "admin":
            event_context(db, news.event_id)
    return obj


@router.get("/sources/{source_id}", response_model=EvidenceOut)
def source(
    source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    obj = accessible_source(db, source_id, user)
    result = EvidenceOut.model_validate(obj).model_dump()
    if obj.kind == "bank":
        result["locator"] = {**obj.locator, "url": f"/sources/{obj.id}/file#page={obj.locator['page']}"}
    if obj.kind == "company":
        from app.services.clients import company_context

        context = company_context(db, obj.company_id)
        field = obj.locator.get("feature_path", "").removeprefix("features.")
        result["locator"] = {
            **obj.locator,
            "value": obj.locator.get(
                "value", context["features"].get(field) if obj.version == context["profile_version"] else None
            ),
            "current_profile_version": context["profile_version"],
            "stale": obj.version != context["profile_version"],
        }
    return result


@router.get("/sources/{source_id}/file")
def source_file(
    source_id: str, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    obj = accessible_source(db, source_id, user)
    if obj.kind != "bank":
        raise AppError(422, "not_pdf", "Источник не является PDF")
    document = db.get(BankDocument, obj.source_id)
    if not document:
        raise AppError(404, "not_found", "Документ не найден")
    root = get_settings().storage_dir.resolve()
    path = (root / document.storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError(404, "not_found", "Файл недоступен")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/feedback", response_model=FeedbackOut)
def feedback(
    body: FeedbackIn, user: User = Depends(current_user), db: Session = Depends(get_db, scope="function")
):
    owned(db, Insight, body.insight_id, user)
    obj = db.scalar(
        select(Feedback).where(Feedback.user_id == user.id, Feedback.insight_id == body.insight_id)
    )
    if not obj:
        obj = Feedback(user_id=user.id, **body.model_dump())
        db.add(obj)
    else:
        obj.rating, obj.comment = (body.rating, body.comment)
    db.flush()
    return {"id": obj.id, "rating": obj.rating}

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import Chat, Insight, Job, Message, User
from app.schemas import (
    ChatIn,
    ChatOut,
    EventIn,
    InsightOut,
    JobOut,
    MessageIn,
    MessageOut,
)
from app.security import company_access, current_user, owned
from app.services.jobs import enqueue, event_context, insight_versions

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
    db: Session = Depends(get_db),
):
    company_access(db, user, company_id)
    versions, key = insight_versions(db, user, company_id, body.event_id)
    previous = db.scalar(select(Insight).where(Insight.cache_key == key))
    if previous:
        return previous
    from fastapi.responses import JSONResponse

    job = enqueue(db, "insight", {"event_id": body.event_id}, user.id, company_id, f"insight:{key}")
    return JSONResponse(status_code=202, content=JobOut.model_validate(job).model_dump(mode="json"))


@router.get("/insights/{insight_id}", response_model=InsightOut)
def get_insight(insight_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned(db, Insight, insight_id, user)


@router.post("/chats", response_model=ChatOut, status_code=201)
def create_chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    company_access(db, user, body.company_id)
    event_context(db, body.event_id)
    chat = Chat(user_id=user.id, **body.model_dump())
    db.add(chat)
    db.flush()
    return chat


@router.post("/chats/{chat_id}/messages", response_model=JobOut, status_code=202)
def send_message(
    chat_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)
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
    db: Session = Depends(get_db),
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

"""Owned chat restoration and idempotent question submission on the existing queue."""

from sqlalchemy import func, select

from app.errors import AppError
from app.models import Chat, Job, Message
from app.services.access import owned
from app.services.events import event_context
from app.services.queue import enqueue


def chat_jobs(chat):
    return select(Job).where(
        Job.kind == "chat",
        Job.user_id == chat.user_id,
        Job.company_id == chat.company_id,
        Job.payload["chat_id"].as_string() == chat.id,
    )


def chat_state(db, user, chat_id):
    chat = owned(db, Chat, chat_id, user)
    event = event_context(db, chat.event_id)
    job = db.scalar(chat_jobs(chat).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
    return dict(
        id=chat.id,
        company_id=chat.company_id,
        event_id=chat.event_id,
        event_title=event["title"],
        last_job=job,
        last_message_id=job.payload.get("message_id") if job else None,
        last_client_message_id=(job.payload.get("client_message_id") or f"legacy_{job.payload['message_id']}")
        if job
        else None,
    )


def submit_question(db, user, chat_id, body):
    chat = owned(db, Chat, chat_id, user)
    db.scalar(select(Chat).where(Chat.id == chat.id).with_for_update())
    event_context(db, chat.event_id)
    previous = None
    if body.client_message_id:
        identity = Job.payload["client_message_id"].as_string() == body.client_message_id
        if body.client_message_id.startswith("legacy_"):
            identity = Job.payload["message_id"].as_string() == body.client_message_id.removeprefix("legacy_")
        previous = db.scalar(
            chat_jobs(chat).where(identity).order_by(Job.created_at.desc(), Job.id.desc()).limit(1)
        )
    latest = db.scalar(select(func.max(Message.sequence)).where(Message.chat_id == chat.id)) or 0
    if previous:
        message = db.get(Message, previous.payload["message_id"])
        if not message or message.text != body.text:
            raise AppError(409, "idempotency_conflict", "Ключ вопроса уже использован с другим текстом")
        if not body.retry or previous.status != "failed":
            return chat, message, previous, False
        if message.sequence != latest:
            raise AppError(409, "retry_not_latest", "Можно повторить только последний неотвеченный вопрос")
    if db.scalar(select(Job.id).where(Job.dedup_key == f"chat:{chat.id}")):
        raise AppError(409, "chat_busy", "Предыдущий вопрос ещё обрабатывается")
    created = previous is None
    if created:
        message = Message(chat_id=chat.id, role="user", text=body.text, sequence=latest + 1)
        db.add(message)
        db.flush()
    job = enqueue(
        db,
        "chat",
        {
            "chat_id": chat.id,
            "event_id": chat.event_id,
            "message_id": message.id,
            "client_message_id": body.client_message_id,
        },
        user.id,
        chat.company_id,
        f"chat:{chat.id}",
    )
    return chat, message, job, created

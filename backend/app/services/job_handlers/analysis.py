"""Company-scoped focus, insight and chat handlers reuse one authorized context."""

from sqlalchemy import select

from app.errors import AppError
from app.insight_provenance import validate_v2_provenance
from app.integrations.ai import AIError, call_ai
from app.models import Chat, Insight, Membership, Message, User
from app.schemas import AIEnvelope, ChatResult, InsightResultV2, parse_insight_result
from app.services.access import company_access
from app.services.clients import company_context
from app.services.events import event_context
from app.services.evidence import check_refs, save_trace, store_evidence
from app.services.focus import derive_focus
from app.services.insights import insight_versions
from app.services.publication import require_publication


def user_context(db, job):
    user = db.get(User, job.user_id, with_for_update=True, populate_existing=True)
    if not user or user.status != "active":
        raise AppError(403, "forbidden", "Доступ отозван")
    membership = company_access(db, user, job.company_id)
    db.scalar(
        select(Membership)
        .where(Membership.id == membership.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    focus = derive_focus(db, membership)
    return user, membership, focus


def analysis_context(db, job):
    user, _, focus = user_context(db, job)
    context = company_context(db, job.company_id)
    event = event_context(db, job.payload["event_id"])
    from app.services.tools import AnalysisTools

    tools = AnalysisTools(db, user.id, job.company_id, event["id"])
    return user, focus, context, event, tools


def focus_job(db, job):
    _, membership, focus = user_context(db, job)
    return {"membership_id": membership.id, "focus": focus}


def insight_job(db, job):
    user, focus, context, event, tools = analysis_context(db, job)
    versions, key = insight_versions(db, user, job.company_id, event["id"])
    expected = job.payload.get("expected_cache_key")
    if expected and key != expected:
        raise AIError("stale_inputs", "Входные данные карточки изменились")
    previous = db.scalar(select(Insight).where(Insight.cache_key == key))
    if previous:
        return {"insight_id": previous.id}
    envelope = AIEnvelope.model_validate(
        call_ai("build_insight", company_context=context, user_focus=focus, event=event, tools=tools)
    )
    parsed = parse_insight_result(envelope.result)
    current, current_key = insight_versions(db, user, job.company_id, event["id"])
    if current_key != key or current != versions:
        raise AIError("stale_inputs", "Входные данные изменились во время генерации")
    if isinstance(parsed, InsightResultV2):
        try:
            validate_v2_provenance(parsed, envelope.evidence)
        except ValueError as exc:
            raise AIError("invalid_evidence", "Некорректные основания карточки v2") from exc
    result = parsed.model_dump(mode="json")
    require_publication(envelope, result, "insight")
    store_evidence(db, envelope, job.company_id)
    check_refs(db, result, job.company_id)
    insight = db.scalar(select(Insight).where(Insight.cache_key == key))
    if not insight:
        insight = Insight(
            user_id=user.id,
            company_id=job.company_id,
            event_id=event["id"],
            cache_key=key,
            versions=versions,
            result=result,
        )
        db.add(insight)
        db.flush()
    save_trace(
        db, result["trace_id"], user, job.company_id, {**envelope.trace, "job_id": getattr(job, "id", None)}
    )
    return {"insight_id": insight.id}


def chat_job(db, job):
    user, focus, context, event, tools = analysis_context(db, job)
    chat = db.get(Chat, job.payload["chat_id"])
    if not chat or chat.user_id != user.id or chat.company_id != job.company_id:
        raise AppError(403, "forbidden", "Диалог недоступен")
    history = list(
        db.scalars(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.sequence.desc()).limit(30)
        )
    )
    envelope = AIEnvelope.model_validate(
        call_ai(
            "answer_chat",
            company_context=context,
            user_focus=focus,
            event=event,
            tools=tools,
            history=[{"role": m.role, "text": m.text} for m in reversed(history)],
        )
    )
    result = ChatResult.model_validate(envelope.result).model_dump(mode="json")
    require_publication(envelope, result, "chat")
    store_evidence(db, envelope, job.company_id)
    check_refs(db, result, job.company_id)
    db.scalar(select(Chat).where(Chat.id == chat.id).with_for_update())
    from sqlalchemy import func

    sequence = (db.scalar(select(func.max(Message.sequence)).where(Message.chat_id == chat.id)) or 0) + 1
    message = Message(
        chat_id=chat.id, role="assistant", text=result["answer"], result=result, sequence=sequence
    )
    db.add(message)
    db.flush()
    db.refresh(user)
    if user.status != "active":
        raise AppError(403, "forbidden", "Доступ отозван")
    company_access(db, user, job.company_id)
    event_context(db, event["id"])
    save_trace(db, result["trace_id"], user, job.company_id, {**envelope.trace, "job_id": job.id})
    return {"message_id": message.id, "chat_id": chat.id}

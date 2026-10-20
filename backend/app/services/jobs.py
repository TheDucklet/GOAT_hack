import hashlib
import json
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import as_utc, session_factory, utcnow
from app.errors import AppError
from app.integrations.ai import AIError, call_ai
from app.models import BankDocument, Chat, Chunk, Event, Evidence, Insight, Job, Message, News, Trace, User
from app.schemas import AIEnvelope, ChatResult, IngestResult, InsightResult, SummaryResult, UserFocus
from app.security import company_access
from app.services.clients import company_context


def enqueue(db, kind, payload, user_id=None, company_id=None, dedup_key=None):
    if dedup_key:
        previous = db.scalar(select(Job).where(Job.dedup_key == dedup_key))
        if previous:
            return previous
    job = Job(kind=kind, payload=payload, user_id=user_id, company_id=company_id, dedup_key=dedup_key)
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session):
    candidate = db.scalar(
        select(Job.id)
        .where(Job.status == "queued", Job.available_at <= utcnow())
        .order_by(Job.available_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if not candidate:
        return None
    claimed = db.scalar(
        update(Job)
        .where(Job.id == candidate, Job.status == "queued")
        .values(status="running", attempts=Job.attempts + 1, started_at=utcnow())
        .returning(Job.id)
    )
    if claimed:
        job = db.get(Job, claimed)
        if job.kind == "ingest_document":
            doc = db.get(BankDocument, job.payload["document_id"])
            if doc:
                doc.status = "running"
    db.commit()
    return claimed


def event_context(db, event_id):
    event = db.get(Event, event_id)
    if not event or not event.visible:
        raise AppError(404, "not_found", "Событие недоступно")
    news = list(db.scalars(select(News).where(News.event_id == event_id)))
    evidence = list(
        db.scalars(
            select(Evidence).where(Evidence.kind == "news", Evidence.source_id.in_([n.id for n in news]))
        )
    )
    return {
        "id": event.id,
        "title": event.title,
        "summary": event.summary,
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "version": event.version,
        "topics": event.topics,
        "facts": event.facts,
        "publications": [{"id": n.id, "url": n.url, "text": n.text} for n in news],
        "evidence": [
            {
                "id": e.id,
                "kind": e.kind,
                "source_id": e.source_id,
                "version": e.version,
                "locator": e.locator,
                "excerpt": e.excerpt,
            }
            for e in evidence
        ],
    }


def derive_focus(db, membership):
    from app.api.companies import focus_hash

    key = focus_hash(membership)
    if membership.focus_input_hash == key and membership.user_focus:
        return membership.user_focus
    focus = UserFocus.model_validate(
        call_ai("derive_user_focus", position_text=membership.position_text, interests=membership.interests)
    ).model_dump(mode="json")
    membership.focus_input_hash, membership.user_focus = (key, focus)
    return focus


def insight_versions(db, user, company_id, event_id):
    membership = company_access(db, user, company_id)
    event = event_context(db, event_id)
    documents = list(
        db.execute(
            select(
                BankDocument.sha256, BankDocument.version, BankDocument.index_version, BankDocument.status
            ).order_by(BankDocument.id)
        )
    )
    from app.api.companies import focus_hash

    versions = {
        "profile": company_context(db, company_id)["profile_version"],
        "event": event["version"],
        "focus": focus_hash(membership),
        "corpus": hashlib.sha256(repr(documents).encode()).hexdigest(),
        "generation": f"{get_settings().ai_module}:{get_settings().ai_generation_version}",
    }
    key = hashlib.sha256(
        json.dumps([user.id, company_id, event_id, versions], sort_keys=True).encode()
    ).hexdigest()
    return (versions, key)


def store_evidence(db, envelope, company_id):
    for item in envelope.evidence:
        if item.kind == "bank":
            doc = db.get(BankDocument, item.source_id)
            page = item.locator.get("page")
            if (
                not doc
                or item.version != doc.version
                or (not isinstance(page, int))
                or (not 1 <= page <= doc.page_count)
            ):
                raise AIError("invalid_evidence", "Некорректный источник PDF")
        elif item.kind == "news":
            news = db.get(News, item.source_id)
            if not news or item.version != news.content_hash:
                raise AIError("invalid_evidence", "Некорректный новостной источник")
        elif item.kind == "company":
            context = company_context(db, company_id)
            path = item.locator.get("feature_path", "")
            field = path.removeprefix("features.")
            if (
                item.source_id != company_id
                or item.version != context["profile_version"]
                or field not in context["features"]
                or (context["features"][field].get("value") is None)
            ):
                raise AIError("invalid_evidence", "Некорректный клиентский источник")
        existing = db.get(Evidence, item.id)
        values = item.model_dump()
        if item.kind == "company":
            values["locator"] = {**values["locator"], "value": context["features"][field]}
        if existing:
            if any((getattr(existing, field) != value for field, value in values.items())):
                raise AIError("invalid_evidence", "Источник с этим ID уже имеет другое содержимое")
            if existing.company_id and existing.company_id != company_id:
                raise AIError("invalid_evidence", "Недоступный клиентский источник")
        else:
            db.add(Evidence(**values, company_id=company_id if item.kind == "company" else None))
    db.flush()


def check_refs(db, result, company_id):
    refs = set(result.get("evidence_refs", []))
    for key in ["facts", "bank_view", "ai_interpretation", "risks", "opportunities", "actions"]:
        for claim in result.get(key) or []:
            if not claim["evidence_refs"]:
                raise AIError("invalid_evidence", "Утверждение не содержит оснований")
            refs.update(claim["evidence_refs"])
    for ref in refs:
        evidence = db.get(Evidence, ref)
        if not evidence or evidence.company_id not in {None, company_id}:
            raise AIError("invalid_evidence", "Источник не найден или недоступен")
    for claim in result.get("bank_view") or []:
        if not any((db.get(Evidence, ref).kind == "bank" for ref in claim["evidence_refs"])):
            raise AIError("invalid_evidence", "Позиция банка не подтверждена банковским материалом")


def execute_job(db, job):
    if job.user_id and job.kind in {"collect_news", "summarize", "ingest_document"}:
        actor = db.get(User, job.user_id)
        if not actor or actor.status != "active" or actor.system_role != "admin":
            raise AppError(403, "forbidden", "Административный доступ отозван")
    if job.kind == "collect_news":
        from app.services.news import collect_news

        result = collect_news(db)
        if not any((s["ok"] for s in result.values())):
            raise AIError("source_fetch_failed", "Все новостные источники недоступны")
        return result
    if job.kind == "summarize":
        event = event_context(db, job.payload["event_id"])
        result = SummaryResult.model_validate(call_ai("summarize_event", event=event)).model_dump(mode="json")
        check_refs(db, result, None)
        obj = db.get(Event, event["id"])
        obj.summary, obj.facts, obj.topics = (result["summary"], result["facts"], result["topics"])
        obj.processing_status = "done"
        return {"event_id": obj.id}
    if job.kind == "ingest_document":
        doc = db.get(BankDocument, job.payload["document_id"])
        if not doc:
            raise AIError("not_found", "Документ не найден")
        from pathlib import Path

        result = IngestResult.model_validate(
            call_ai(
                "ingest_bank_document",
                document={
                    "id": doc.id,
                    "version": doc.version,
                    "page_count": doc.page_count,
                    "filename": doc.filename,
                },
                path=str(Path(get_settings().storage_dir).resolve() / doc.storage_key),
            )
        )
        checked = []
        for chunk in result.chunks:
            page = chunk.get("page")
            if (
                not isinstance(page, int)
                or not 1 <= page <= doc.page_count
                or (not chunk.get("text", "").strip())
            ):
                raise AIError("invalid_ocr", "OCR вернул некорректную страницу")
            checked.append(
                Chunk(
                    document_id=doc.id,
                    version=doc.version,
                    page=page,
                    text=chunk["text"],
                    quality=chunk.get("quality", {}),
                )
            )
        if {c.page for c in checked} != set(range(1, doc.page_count + 1)):
            raise AIError("invalid_ocr", "OCR не содержит текст всех страниц")
        from sqlalchemy import delete

        db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
        db.add_all(checked)
        doc.index_version = hashlib.sha256(
            json.dumps(result.model_dump(), sort_keys=True).encode()
        ).hexdigest()
        doc.document_date, doc.status, doc.error = (result.document_date, "done", None)
        return {"document_id": doc.id, "chunks": len(checked)}
    user = db.get(User, job.user_id)
    if not user or user.status != "active":
        raise AppError(403, "forbidden", "Доступ отозван")
    membership = company_access(db, user, job.company_id)
    focus = derive_focus(db, membership)
    if job.kind == "focus":
        return {"membership_id": membership.id, "focus": focus}
    context = company_context(db, job.company_id)
    event = event_context(db, job.payload["event_id"])
    from app.services.tools import AnalysisTools

    tools = AnalysisTools(db, user.id, job.company_id, event["id"])
    if job.kind == "insight":
        versions, key = insight_versions(db, user, job.company_id, event["id"])
        envelope = AIEnvelope.model_validate(
            call_ai("build_insight", company_context=context, user_focus=focus, event=event, tools=tools)
        )
        result = InsightResult.model_validate(envelope.result).model_dump(mode="json")
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
        save_trace(db, result["trace_id"], user, job.company_id, envelope.trace)
        return {"insight_id": insight.id}
    if job.kind == "chat":
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
        save_trace(db, result["trace_id"], user, job.company_id, envelope.trace)
        return {"message_id": message.id, "chat_id": chat.id}
    raise AIError("unknown_job", "Неизвестный тип задания")


def save_trace(db, trace_id, user, company_id, trace):
    if db.get(Trace, trace_id):
        raise AIError("trace_conflict", "Трасса с этим ID уже существует")
    db.add(Trace(id=trace_id, user_id=user.id, company_id=company_id, result=trace))


def run_one() -> bool:
    with session_factory()() as db:
        job_id = claim_next(db)
        if not job_id:
            return False
        job = db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        try:
            with db.begin_nested():
                result = execute_job(db, job)
                job.result, job.status, job.error = (result, "done", None)
            job.finished_at, job.dedup_key = (utcnow(), None)
        except Exception as exc:
            db.expire(job)
            code = exc.code if isinstance(exc, (AIError, AppError)) else "processing_failed"
            message = exc.message if isinstance(exc, (AIError, AppError)) else "Ошибка обработки задания"
            job.error = {"code": code, "message": message, "request_id": job.id}
            transient = code in {"source_fetch_failed", "timeout", "rate_limited", "provider_unavailable"}
            if transient and job.attempts < 3:
                job.status, job.available_at = ("queued", utcnow() + timedelta(seconds=5 * 2**job.attempts))
            else:
                job.status, job.finished_at, job.dedup_key = ("failed", utcnow(), None)
                if job.kind == "ingest_document":
                    doc = db.get(BankDocument, job.payload["document_id"])
                    if doc:
                        doc.status, doc.error = ("failed", code)
                if job.kind == "summarize":
                    event = db.get(Event, job.payload["event_id"])
                    if event:
                        event.processing_status = "failed"
        db.commit()
        return True


def scheduler_tick(db):
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        if not db.scalar(text("SELECT pg_try_advisory_xact_lock(761202602)")):
            return
    now = utcnow()
    last = db.scalar(
        select(Job.created_at).where(Job.kind == "collect_news").order_by(Job.created_at.desc()).limit(1)
    )
    if not last or now - as_utc(last) >= timedelta(minutes=get_settings().news_poll_minutes):
        enqueue(db, "collect_news", {}, dedup_key="collect_news")
    stale = db.scalars(
        select(Job)
        .where(
            Job.status == "running",
            Job.started_at < now - timedelta(seconds=get_settings().job_timeout_seconds),
        )
        .with_for_update(skip_locked=True)
    )
    for job in stale:
        job.status, job.dedup_key, job.finished_at = ("failed", None, now)
        job.error = {
            "code": "worker_lost",
            "message": "Задание прервано; доступен ручной повтор",
            "request_id": job.id,
        }
        if job.kind == "ingest_document":
            document = db.get(BankDocument, job.payload.get("document_id"))
            if document:
                document.status, document.error = ("failed", "worker_lost")
        elif job.kind == "summarize":
            event = db.get(Event, job.payload.get("event_id"))
            if event:
                event.processing_status = "failed"

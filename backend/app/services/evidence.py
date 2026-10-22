"""Shared evidence validation and trace persistence for all AI results."""

from zoneinfo import ZoneInfo

from app.ai.rag.temporal import temporal_status
from app.data_semantics import confirmed_value
from app.db import utcnow
from app.integrations.ai import AIError
from app.models import BankDocument, Evidence, News, Trace
from app.services.clients import company_context


def bank_locator(db, evidence):
    document = db.get(BankDocument, evidence.source_id)
    locator = dict(evidence.locator)
    day = utcnow().astimezone(ZoneInfo("Europe/Moscow")).date()
    date = locator.get("document_date")
    if document and document.version == evidence.version:
        date = date or document.document_date
    try:
        status, reason = temporal_status(date, evidence.excerpt, day)
    except (ValueError, TypeError):
        status, reason = "undated", "Дата документа неизвестна"
    if not document or document.version != evidence.version:
        status, reason = "source_changed", "Версия документа изменилась или недоступна"
    return {
        **locator,
        "document_date": date,
        "temporal_status": status,
        "temporal_reason": reason,
        "evaluated_on": day.isoformat(),
    }


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
                or confirmed_value(context["features"][field]) is None
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


def save_trace(db, trace_id, user, company_id, trace):
    if db.get(Trace, trace_id):
        raise AIError("trace_conflict", "Трасса с этим ID уже существует")
    db.add(Trace(id=trace_id, user_id=user.id, company_id=company_id, result=trace))

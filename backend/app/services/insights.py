"""Insight input versions and cache identity; no queue or HTTP dependency."""

import hashlib
import json

from sqlalchemy import select

from app.config import get_settings
from app.errors import AppError
from app.insight_versions import contract_versions
from app.models import BankDocument, Company, Event
from app.services.access import company_access
from app.services.events import event_version
from app.services.focus import focus_hash
from app.services.generation_metadata import generation_versions


def company_versions(db, user, company_id):
    membership = company_access(db, user, company_id)
    documents = list(
        db.execute(
            select(
                BankDocument.sha256,
                BankDocument.version,
                BankDocument.index_version,
                BankDocument.status,
                BankDocument.document_date,
            ).order_by(BankDocument.id)
        )
    )
    company = db.get(Company, company_id, populate_existing=True)
    versions = {
        **contract_versions(company.data_semantics_version),
        **generation_versions(),
        "profile": company.profile_version,
        "focus": focus_hash(membership),
        "corpus": hashlib.sha256(repr(documents).encode()).hexdigest(),
        "generation": f"{get_settings().ai_module}:{get_settings().ai_generation_version}",
    }
    return versions


def insight_key(user_id, company_id, event_id, versions):
    return hashlib.sha256(
        json.dumps([user_id, company_id, event_id, versions], sort_keys=True).encode()
    ).hexdigest()


def insight_versions(db, user, company_id, event_id):
    versions = company_versions(db, user, company_id)
    event = db.get(Event, event_id, populate_existing=True)
    if not event or not event.visible:
        raise AppError(404, "not_found", "Событие недоступно")
    versions["event"] = event_version(event)
    key = insight_key(user.id, company_id, event_id, versions)
    return (versions, key)

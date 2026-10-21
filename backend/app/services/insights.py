"""Insight input versions and cache identity; no queue or HTTP dependency."""

import hashlib
import json

from sqlalchemy import select

from app.config import get_settings
from app.insight_versions import contract_versions
from app.models import BankDocument
from app.services.access import company_access
from app.services.clients import company_context
from app.services.events import event_context
from app.services.focus import focus_hash


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
    versions = {
        **contract_versions(),
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

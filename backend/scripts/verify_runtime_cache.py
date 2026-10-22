"""Verify the installed AI cache in a fresh process without exporting client contents."""

import json

from sqlalchemy import select

from app.ai.bridge import build_insight
from app.ai.providers.budgeting import default_ledger
from app.ai.providers.settings import get_llm_settings
from app.db import session_factory
from app.models import Insight, Membership
from app.services.clients import company_context
from app.services.events import event_context
from app.services.tools import AnalysisTools


def main():
    budget = default_ledger(get_llm_settings())
    before = budget.status()
    with session_factory()() as db:
        insight = db.scalar(select(Insight).order_by(Insight.created_at.desc()).limit(1))
        assert insight is not None
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == insight.user_id, Membership.company_id == insight.company_id
            )
        )
        envelope = build_insight(
            company_context(db, insight.company_id),
            membership.user_focus,
            event_context(db, insight.event_id),
            AnalysisTools(db, insight.user_id, insight.company_id, insight.event_id),
        )
        result = {
            "cache_hit": envelope["trace"].get("cache", {}).get("hit", False),
            "fresh_trace_id": envelope["result"]["trace_id"] != insight.result["trace_id"],
            "before_rub": before["spent_rub"],
            "after_rub": budget.status()["spent_rub"],
        }
        assert (
            result["cache_hit"] and result["fresh_trace_id"] and result["before_rub"] == result["after_rub"]
        )
    print(json.dumps(result))


if __name__ == "__main__":
    main()

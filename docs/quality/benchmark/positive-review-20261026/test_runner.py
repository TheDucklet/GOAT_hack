from datetime import UTC, date, datetime, timedelta

import pytest
from run_review import RunBudgetConfig

from app.ai.budget import BudgetExhausted, BudgetLedger


def test_one_run_cannot_receive_another_budget_after_three_am(tmp_path):
    moment = [datetime(2026, 10, 25, 23, 59, tzinfo=UTC)]
    config = RunBudgetConfig(daily_limit_rub=15, anchored_day=date(2026, 10, 25))
    ledger = BudgetLedger(config, tmp_path / "review.jsonl", clock=lambda: moment[0])
    first = ledger.reserve("one", 10)
    ledger.settle(first, 10, "synthetic", "fake", "ok")
    moment[0] += timedelta(days=1)
    with pytest.raises(BudgetExhausted):
        ledger.reserve("would_exceed_total", 6)
    assert ledger.status()["spent_rub"] == 10
    assert ledger.status()["remaining_rub"] == 5


def test_restart_keeps_spending_and_unresolved_reservations(tmp_path):
    config = RunBudgetConfig(daily_limit_rub=15, anchored_day=date(2026, 10, 25))
    path = tmp_path / "review.jsonl"
    ledger = BudgetLedger(config, path)
    first = ledger.reserve("settled", 6)
    ledger.settle(first, 6, "synthetic", "fake", "ok")
    ledger.reserve("in_flight", 5)
    restored = BudgetLedger(config, path)
    with pytest.raises(BudgetExhausted):
        restored.reserve("extra", 5)
    assert restored.status()["spent_rub"] == 6
    assert restored.status()["reserved_rub"] == 5

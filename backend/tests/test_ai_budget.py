import json
import threading
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.ai.budget import BudgetConfig, BudgetExhausted, BudgetLedger
from app.ai.budget.__main__ import main as budget_main
from app.ai.providers import LLMInput, LLMSettings, MemoryUsageSink, TariffTable, call_llm
from app.ai.providers.budgeting import default_ledger, estimate_cost_rub, shared_ledger
from app.ai.providers.models import LLMRequest
from app.ai.providers.testing import ScriptedTransport, completion, http_error, json_completion
from app.ai.providers.transport import TransportFailure

MSK = timezone(timedelta(hours=3))
TASK = "derive_user_focus"
INPUT = LLMInput(system="Система", user="Вопрос пользователя")


def llm_settings(**overrides):
    return LLMSettings(_env_file=None, llm_api_key="sk-test", llm_retry_backoff_seconds=0, **overrides)


def ledger(limit=500.0, path=None, now=None):
    config = BudgetConfig(daily_limit_rub=limit)
    moment = now or datetime(2026, 10, 24, 12, 0, tzinfo=MSK)
    return BudgetLedger(config, path, clock=lambda: moment)


def call(budget, transport, sink=None, **options):
    return call_llm(
        TASK,
        INPUT,
        options.pop("max_tokens", 100),
        settings=llm_settings(),
        transport=transport,
        usage_sink=sink or MemoryUsageSink(),
        budget=budget,
        sleep=lambda seconds: None,
        **options,
    )


def one_call_cost():
    tariffs = TariffTable.load(llm_settings().llm_tariffs_path)
    return tariffs.cost_rub(llm_settings().llm_task_models[TASK], 100, 50)


def test_reservation_estimate_counts_max_tokens_and_images():
    tariffs = TariffTable.load(llm_settings().llm_tariffs_path)
    model = llm_settings().llm_task_models[TASK]

    def request(max_tokens, images=()):
        return LLMRequest(
            request_id="r",
            model_id=model,
            system="а" * 100,
            user="б" * 100,
            image_data_urls=images,
            max_tokens=max_tokens,
            temperature=0,
            json_mode=True,
        )

    config = BudgetConfig()
    small = estimate_cost_rub(tariffs, config, request(100))
    large = estimate_cost_rub(tariffs, config, request(4000))
    with_image = estimate_cost_rub(tariffs, config, request(100, ("data:image/png;base64,AA",)))
    assert small == tariffs.cost_rub(model, 100, 100)
    assert large > small
    assert with_image > small


def test_successful_call_settles_the_actual_usage():
    budget = ledger()
    transport = ScriptedTransport(json_completion({"themes": []}, 100, 50))
    call(budget, transport)
    status = budget.status()
    assert status["spent_rub"] == pytest.approx(one_call_cost())
    assert status["reserved_rub"] == 0
    assert status["remaining_rub"] == pytest.approx(500 - one_call_cost())


def test_gateway_cost_replaces_the_estimate():
    budget = ledger()
    transport = ScriptedTransport(completion('{"a": 1}', 10, 10, cost=0.5))
    call(budget, transport)
    assert budget.status()["spent_rub"] == pytest.approx(0.5)


def test_exhausted_budget_returns_error_without_calling_the_model():
    budget = ledger(limit=0.000001)
    transport = ScriptedTransport()
    sink = MemoryUsageSink()
    with pytest.raises(Exception) as raised:
        call(budget, transport, sink)
    assert raised.value.code == "budget_exhausted"
    assert "лимит" in raised.value.message.lower()
    assert transport.calls == 0
    assert sink.records[0].status == "budget_exhausted" and sink.records[0].cost_rub == 0


def test_limit_is_shared_by_consecutive_calls_and_then_blocks_new_ones():
    cost = one_call_cost()
    budget = ledger(limit=cost * 2.5)
    transport = ScriptedTransport(*[json_completion({"themes": []}, 100, 50) for _ in range(5)])
    call(budget, transport)
    call(budget, transport)
    with pytest.raises(Exception) as raised:
        call(budget, transport)
    assert raised.value.code == "budget_exhausted"
    assert transport.calls == 2


def test_reservation_with_large_max_tokens_blocks_before_the_actual_spend_would():
    budget = ledger(limit=0.001)
    transport = ScriptedTransport(json_completion({"themes": []}, 10, 10))
    with pytest.raises(Exception) as raised:
        call(budget, transport, max_tokens=4000)
    assert raised.value.code == "budget_exhausted" and transport.calls == 0
    assert budget.status()["exhausted"] is False


def test_timeout_keeps_conservative_spend_and_releases_reservation():
    budget = ledger()
    transport = ScriptedTransport(*[TransportFailure("timeout")] * 3)
    with pytest.raises(Exception):
        call(budget, transport)
    status = budget.status()
    assert status["spent_rub"] > 0 and status["reserved_rub"] == 0


def test_retry_reserves_again_and_stops_before_an_over_budget_call():
    budget = ledger(limit=0.003)
    transport = ScriptedTransport(TransportFailure("timeout"), json_completion({"ok": True}, 10, 10))
    with pytest.raises(Exception) as raised:
        call(budget, transport)
    assert raised.value.code == "budget_exhausted"
    assert transport.calls == 1
    assert budget.status()["spent_rub"] > 0
    assert budget.status()["reserved_rub"] == 0


def test_invalid_json_response_is_still_billed():
    budget = ledger()
    transport = ScriptedTransport(completion("не json", 100, 50))
    with pytest.raises(Exception) as raised:
        call(budget, transport)
    assert raised.value.code == "invalid_json"
    assert budget.status()["spent_rub"] == pytest.approx(one_call_cost())


def test_gateway_budget_error_closes_the_day_for_later_calls():
    budget = ledger()
    transport = ScriptedTransport(http_error(400, '{"error": "Budget has been exceeded"}'))
    with pytest.raises(Exception) as first:
        call(budget, transport)
    assert first.value.code == "budget_exhausted"
    with pytest.raises(Exception) as second:
        call(budget, transport)
    assert second.value.code == "budget_exhausted"
    assert transport.calls == 1
    assert budget.status()["exhausted"] is True and budget.status()["remaining_rub"] == 0


def test_budget_day_follows_moscow_time_and_resets_at_three():
    config = BudgetConfig()
    before = config.day_of(datetime(2026, 10, 24, 2, 59, tzinfo=MSK))
    after = config.day_of(datetime(2026, 10, 24, 3, 0, tzinfo=MSK))
    assert (after - before).days == 1
    assert config.day_of(datetime(2026, 10, 23, 23, 59, tzinfo=UTC)) == before
    assert config.day_of(datetime(2026, 10, 24, 0, 0, tzinfo=UTC)) == after


def test_spent_amount_does_not_carry_over_to_the_next_day():
    clock = {"now": datetime(2026, 10, 24, 12, 0, tzinfo=MSK)}
    budget = BudgetLedger(BudgetConfig(daily_limit_rub=1), clock=lambda: clock["now"])
    reservation = budget.reserve("r1", 0.4)
    budget.settle(reservation, 0.9, TASK, "m", "ok")
    with pytest.raises(BudgetExhausted):
        budget.reserve("r2", 0.2)
    clock["now"] = datetime(2026, 10, 25, 3, 0, tzinfo=MSK)
    assert budget.reserve("r3", 0.2).amount_rub == 0.2
    assert budget.status()["spent_rub"] == 0


def test_ledger_survives_restart_through_the_journal(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first = ledger(limit=1, path=path)
    first.settle(first.reserve("r1", 0.3), 0.7, TASK, "model", "ok")
    second = ledger(limit=1, path=path)
    assert second.status()["spent_rub"] == pytest.approx(0.7)
    with pytest.raises(BudgetExhausted):
        second.reserve("r2", 0.4)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert lines[0]["event"] == "reserved"
    assert lines[1]["request_id"] == "r1" and lines[1]["task"] == TASK and lines[1]["cost_rub"] == 0.7


def test_exhausted_marker_survives_restart(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger(path=path).mark_exhausted()
    with pytest.raises(BudgetExhausted):
        ledger(path=path).reserve("r", 0.000001)


def test_parallel_reservations_never_exceed_the_limit():
    budget = ledger(limit=3)
    accepted = []

    def reserve(index):
        try:
            accepted.append(budget.reserve(f"r{index}", 1))
        except BudgetExhausted:
            pass

    threads = [threading.Thread(target=reserve, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(accepted) == 3


def test_settings_override_the_default_limit_and_the_ledger_is_shared():
    shared_ledger.cache_clear()
    settings = llm_settings(llm_daily_limit_rub=42)
    assert default_ledger(settings).config.daily_limit_rub == 42
    assert default_ledger(settings) is default_ledger(settings)
    assert default_ledger(llm_settings()).config.daily_limit_rub == 500


def test_shipped_limits_use_five_hundred_rubles_and_moscow_time():
    config = BudgetConfig.load()
    assert config.daily_limit_rub == 500 and config.utc_offset_hours == 3


def test_status_command_prints_today_state(tmp_path, capsys):
    path = tmp_path / "ledger.jsonl"
    code = budget_main(["status", "--ledger", str(path)])
    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["limit_rub"] == 500 and printed["spent_rub"] == 0

import multiprocessing
from pathlib import Path

import pytest

from app.ai.budget import BudgetConfig, BudgetExhausted, BudgetLedger
from app.ai.cache import FileStore, ResultCache, make_key


def reserve_in_process(path, output, index):
    ledger = BudgetLedger(BudgetConfig(daily_limit_rub=3), Path(path))
    try:
        ledger.reserve(str(index), 1)
        output.put(True)
    except BudgetExhausted:
        output.put(False)


def cache_in_process(root, output):
    cache = ResultCache(FileStore(Path(root)))
    key = make_key("focus", version="process-test")
    output.put(cache.fetch(key, lambda: {"producer": multiprocessing.current_process().pid}))


def test_budget_reserves_are_atomic_across_processes_and_restart(tmp_path):
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    path = tmp_path / "ledger.jsonl"
    processes = [context.Process(target=reserve_in_process, args=(str(path), output, i)) for i in range(8)]
    for process in processes:
        process.start()
    results = [output.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert sum(results) == 3
    restarted = BudgetLedger(BudgetConfig(daily_limit_rub=3), path)
    assert restarted.status()["reserved_rub"] == 3
    with pytest.raises(BudgetExhausted):
        restarted.reserve("after-restart", 0.01)


def test_settlement_is_idempotent_and_visible_to_other_instances(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first = BudgetLedger(BudgetConfig(), path)
    second = BudgetLedger(BudgetConfig(), path)
    reservation = first.reserve("request", 1)
    second.settle(reservation, 0.4, "test", "model", "ok")
    first.settle(reservation, 0.4, "test", "model", "ok")
    assert second.status()["spent_rub"] == 0.4
    assert first.status()["reserved_rub"] == 0


def test_file_cache_computes_once_across_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    processes = [context.Process(target=cache_in_process, args=(str(tmp_path), output)) for _ in range(4)]
    for process in processes:
        process.start()
    values = [output.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert sum(not hit for _, hit in values) == 1
    assert len({value["producer"] for value, _ in values}) == 1


def test_gateway_and_job_retries_have_a_combined_bound(env, monkeypatch):
    from app.ai.providers import LLMInput, LLMSettings, MemoryUsageSink, call_llm
    from app.ai.providers.testing import ScriptedTransport
    from app.ai.providers.transport import TransportFailure
    from app.db import session_factory, utcnow
    from app.models import Job
    from app.services.job_handlers import HANDLERS
    from app.services.jobs import run_one
    from app.services.queue import enqueue

    transport = ScriptedTransport(*[TransportFailure("timeout") for _ in range(9)])
    budget = BudgetLedger(BudgetConfig())

    def handler(db, job):
        return call_llm(
            "derive_user_focus",
            LLMInput(system="Synthetic", user="Synthetic"),
            50,
            settings=LLMSettings(_env_file=None, llm_api_key="sk-test", llm_max_retries=2),
            transport=transport,
            budget=budget,
            usage_sink=MemoryUsageSink(),
            sleep=lambda _: None,
        )

    monkeypatch.setitem(HANDLERS, "retry_probe", (handler, False))
    with session_factory()() as db, db.begin():
        job_id = enqueue(db, "retry_probe", {}).id
    for _ in range(3):
        with session_factory()() as db, db.begin():
            db.get(Job, job_id).available_at = utcnow()
        assert run_one()
    with session_factory()() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and job.attempts == 3
        assert job.error["code"] == "timeout"
    assert transport.calls == 9
    assert budget.status()["spent_rub"] > 0 and budget.status()["reserved_rub"] == 0

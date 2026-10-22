import json
import threading

import pytest

from app.ai.budget import BudgetConfig, BudgetLedger
from app.ai.cache import FileStore, MemoryStore, ResultCache, make_key
from app.ai.cache import calls as calls_module
from app.ai.cache.calls import (
    cached_build_insight,
    cached_derive_user_focus,
    cached_summarize_event,
    corpus_version_of,
)
from app.ai.ocr.engine import _cache_file, _load_cached
from app.ai.providers import LLMSettings, MemoryUsageSink, call_llm
from app.ai.providers.testing import ScriptedTransport, json_completion
from tests.test_ai_summaries import event, focus_answer, raw_answer
from tests.test_ai_summaries import focus_module as _focus_module  # noqa: F401
from tests.test_ai_summaries import summarize_module as _summarize_module  # noqa: F401

COMPANY = {"company_id": "U_1", "profile_version": "csv-1"}
EVENT = {"id": "event-1", "version": "v1", "title": "Заголовок"}
FOCUS = {"topics": ["ключевая ставка"], "priorities": ["кредиты"], "unknowns": [], "version": "focus-1"}


class Tools:
    def __init__(self, corpus="corpus-1"):
        self.corpus = corpus

    def corpus_version(self):
        return self.corpus


class NoCorpusTools:
    pass


def envelope():
    return {"result": {"facts": []}, "evidence": [], "trace": {"steps": []}}


@pytest.fixture
def agent(monkeypatch):
    counter = {"runs": 0}

    def fake_run_agent(company_context, user_focus, event_payload, tools):
        counter["runs"] += 1
        return envelope()

    monkeypatch.setattr(calls_module, "build_impact_insight", fake_run_agent)
    return counter


def insight(cache, company=COMPANY, focus=FOCUS, event_payload=EVENT, tools=None, settings=None):
    return cached_build_insight(
        company, focus, event_payload, tools if tools is not None else Tools(), cache, settings
    )


def settings(**task_models):
    base = LLMSettings(_env_file=None, llm_api_key="sk-test")
    return base.model_copy(update={"llm_task_models": {**base.llm_task_models, **task_models}})


def test_repeated_insight_request_does_not_run_the_agent_again(agent):
    cache = ResultCache()
    first = insight(cache)
    second = insight(cache)
    assert agent["runs"] == 1
    assert second["result"] == first["result"]
    assert second["trace"]["cache"]["hit"] is True and "cache" not in first["trace"]
    assert cache.stats() == {"insight.miss": 1, "insight.hit": 1}


@pytest.mark.parametrize(
    "change",
    [
        {"company": {**COMPANY, "company_id": "U_2"}},
        {"company": {**COMPANY, "profile_version": "csv-2"}},
        {"company": {**COMPANY, "data_semantics_version": "normalized-company-2"}},
        {"event_payload": {**EVENT, "version": "v2"}},
        {"event_payload": {**EVENT, "id": "event-2"}},
        {"focus": {**FOCUS, "topics": ["налоги"]}},
        {"focus": {**FOCUS, "priorities": []}},
        {"tools": Tools("corpus-2")},
        {"settings": settings(build_insight="google/gemma-4-26b-a4b-it")},
        {"settings": settings(agent_plan="google/gemma-4-26b-a4b-it")},
    ],
)
def test_changed_input_version_creates_a_new_cache_key(agent, change):
    cache = ResultCache()
    insight(cache)
    insight(cache, **change)
    assert agent["runs"] == 2


def test_changed_prompt_version_excludes_the_old_card(agent, monkeypatch):
    cache = ResultCache()
    insight(cache)
    monkeypatch.setattr(calls_module, "INSIGHT_PROMPT_VERSION", "insight-99")
    insight(cache)
    assert agent["runs"] == 2


@pytest.mark.parametrize(
    "name", ["INSIGHT_CONTRACT_VERSION", "INSIGHT_SCHEMA_VERSION", "DATA_SEMANTICS_VERSION", "POLICY_VERSION"]
)
def test_changed_contract_version_excludes_the_old_card(agent, monkeypatch, name):
    from app import insight_versions

    cache = ResultCache()
    insight(cache)
    monkeypatch.setattr(insight_versions, name, "new-version")
    insight(cache)
    assert agent["runs"] == 2


def test_changed_validation_version_excludes_the_old_card(agent, monkeypatch):
    cache = ResultCache()
    insight(cache)
    monkeypatch.setattr(calls_module, "VALIDATION_VERSION", "validation-99")
    insight(cache)
    assert agent["runs"] == 2


def test_tools_without_corpus_version_bypass_the_card_cache(agent):
    cache = ResultCache()
    insight(cache, tools=NoCorpusTools())
    insight(cache, tools=NoCorpusTools())
    assert agent["runs"] == 2
    assert cache.stats() == {"insight.bypass": 2}
    assert corpus_version_of(NoCorpusTools()) is None and corpus_version_of(Tools()) == "corpus-1"


def test_cached_card_is_a_copy_that_callers_cannot_corrupt(agent):
    cache = ResultCache()
    insight(cache)["result"]["facts"].append("changed")
    assert insight(cache)["result"]["facts"] == []


def test_failed_computation_is_not_cached():
    cache = ResultCache()
    key = make_key("insight", a=1)
    attempts = []

    def compute():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    with pytest.raises(RuntimeError):
        cache.fetch(key, compute)
    assert cache.fetch(key, compute) == ({"ok": True}, False)
    assert cache.fetch(key, compute) == ({"ok": True}, True)
    assert len(attempts) == 2


def test_disabled_cache_always_computes():
    cache = ResultCache(enabled=False)
    key = make_key("insight", a=1)
    counter = []
    cache.fetch(key, lambda: counter.append(1) or {"v": 1})
    cache.fetch(key, lambda: counter.append(1) or {"v": 1})
    assert len(counter) == 2 and cache.stats() == {"insight.bypass": 2}


def test_concurrent_identical_requests_compute_once():
    cache = ResultCache()
    key = make_key("insight", a=1)
    counter = []
    gate = threading.Event()

    def compute():
        counter.append(1)
        gate.wait(0.2)
        return {"v": 1}

    threads = [threading.Thread(target=cache.fetch, args=(key, compute)) for _ in range(6)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join()
    assert len(counter) == 1


def test_keys_are_stable_and_depend_on_every_part():
    assert make_key("k", a=1, b={"x": [1, 2]}).digest == make_key("k", b={"x": [1, 2]}, a=1).digest
    assert make_key("k", a=1).digest != make_key("k", a=2).digest
    assert make_key("k", a=1).digest != make_key("other", a=1).digest


def test_file_store_survives_a_new_process_and_ignores_damaged_files(tmp_path):
    key = make_key("summary", a=1)
    ResultCache(FileStore(tmp_path)).fetch(key, lambda: {"v": 1})
    cache = ResultCache(FileStore(tmp_path))
    assert cache.fetch(key, lambda: {"v": 2}) == ({"v": 1}, True)
    stored = next(tmp_path.rglob("*.json"))
    assert json.loads(stored.read_text(encoding="utf-8"))["parts"] == {"a": 1}
    stored.write_text("{ damaged", encoding="utf-8")
    assert ResultCache(FileStore(tmp_path)).fetch(key, lambda: {"v": 3}) == ({"v": 3}, False)


def test_memory_store_evicts_the_oldest_entry():
    store = MemoryStore(max_items=2)
    keys = [make_key("k", n=n) for n in range(3)]
    for index, key in enumerate(keys):
        store.put(key, {"n": index})
    assert store.get(keys[0]) is None and store.get(keys[2]) == {"n": 2}


def llm_settings():
    return LLMSettings(_env_file=None, llm_api_key="sk-test", llm_retry_backoff_seconds=0)


def patch_llm(monkeypatch, transport, budget=None):
    def patched(task, input, max_tokens, **kwargs):
        return call_llm(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=transport,
            usage_sink=MemoryUsageSink(),
            budget=budget,
            sleep=lambda seconds: None,
            **kwargs,
        )

    for module in (_summarize_module, _focus_module):
        monkeypatch.setattr(module, "call_llm", patched)


def test_repeated_focus_request_does_not_call_the_model(monkeypatch):
    transport = ScriptedTransport(focus_answer(["ключевая ставка"], ["кредиты"]))
    patch_llm(monkeypatch, transport)
    cache = ResultCache()
    first = cached_derive_user_focus("Главный бухгалтер", [], cache)
    second = cached_derive_user_focus("  Главный   бухгалтер ", [], cache)
    assert transport.calls == 1 and first == second


def test_changed_position_calls_the_model_again(monkeypatch):
    transport = ScriptedTransport(
        focus_answer(["ключевая ставка"], []), focus_answer(["бюджет и налоги"], [])
    )
    patch_llm(monkeypatch, transport)
    cache = ResultCache()
    cached_derive_user_focus("Главный бухгалтер", [], cache)
    other = cached_derive_user_focus("Финансовый директор", [], cache)
    assert transport.calls == 2 and other["topics"] == ["бюджет и налоги"]


def test_changed_interests_calls_the_model_again(monkeypatch):
    transport = ScriptedTransport(
        focus_answer(["ключевая ставка"], []), focus_answer(["ключевая ставка"], [])
    )
    patch_llm(monkeypatch, transport)
    cache = ResultCache()
    cached_derive_user_focus("Главный бухгалтер", [], cache)
    cached_derive_user_focus("Главный бухгалтер", ["налоги"], cache)
    assert transport.calls == 2


def test_repeated_summary_request_does_not_call_the_model(monkeypatch):
    transport = ScriptedTransport(json_completion(raw_answer()), json_completion(raw_answer()))
    patch_llm(monkeypatch, transport)
    cache = ResultCache()
    first = cached_summarize_event(event(), cache)
    again = cached_summarize_event(event(), cache)
    assert transport.calls == 1 and first == again


def test_changed_event_version_or_text_calls_the_model_again(monkeypatch):
    transport = ScriptedTransport(*[json_completion(raw_answer()) for _ in range(3)])
    patch_llm(monkeypatch, transport)
    cache = ResultCache()
    cached_summarize_event(event(), cache)
    cached_summarize_event({**event(), "version": "v2"}, cache)
    cached_summarize_event(event(text=event()["publications"][0]["text"] + " Дополнение."), cache)
    assert transport.calls == 3


def test_cached_summary_costs_nothing_even_when_the_budget_is_exhausted(monkeypatch):
    budget = BudgetLedger(BudgetConfig(daily_limit_rub=1.0))
    transport = ScriptedTransport(json_completion(raw_answer()))
    patch_llm(monkeypatch, transport, budget)
    cache = ResultCache()
    cached_summarize_event(event(), cache)
    budget.mark_exhausted()
    cached_summarize_event(event(), cache)
    assert transport.calls == 1
    with pytest.raises(Exception) as raised:
        cached_summarize_event({**event(), "version": "v2"}, cache)
    assert raised.value.code == "budget_exhausted" and transport.calls == 1


def test_ocr_cache_is_not_reused_for_another_model(tmp_path):
    path = _cache_file(tmp_path, "sha", 1)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "text": "текст",
                "title": None,
                "date_text": None,
                "engine": "qwen/qwen3-vl-30b-a3b-instruct",
                "input_tokens": 1,
                "output_tokens": 1,
                "cost_rub": 0.1,
            }
        ),
        encoding="utf-8",
    )
    assert _load_cached(tmp_path, "sha", 1, "qwen/qwen3-vl-30b-a3b-instruct").text == "текст"
    assert _load_cached(tmp_path, "sha", 1, "google/gemma-4-26b-a4b-it") is None

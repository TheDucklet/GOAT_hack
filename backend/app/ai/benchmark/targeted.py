import copy
import os
from pathlib import Path

from app.ai.benchmark.data import BenchmarkContext
from app.ai.benchmark.runner import DEFAULT_FIXTURES, read, run_pair, write
from app.ai.cache import ResultCache
from app.ai.cache import calls as cache_calls
from app.ai.insights.local_tools import repository_search
from app.ai.providers import LLMError, get_llm_settings
from app.ai.providers.budgeting import shared_ledger
from app.ai.providers.gateway import shared_transport
from app.ai.rag.file_repository import FileRepository

KEY_RATE = "ev-cbr-key-rate-2026-10-23"
CONTEXT = "B01-chief_accountant"
OFFLINE_ENV = {"AI_LLM_API_KEY": "sk-offline-check"}


def pick(run_dir: Path, contexts: list[BenchmarkContext]):
    context = next(item for item in contexts if item.context_id == CONTEXT)
    events = {item["id"]: item for item in read(run_dir / "events.json")}
    focus = read(run_dir / "focuses.json")[context.role]
    return context, events[KEY_RATE], focus


def historical_bank(run_dir, contexts, fixtures=DEFAULT_FIXTURES) -> dict:
    context, event, focus = pick(run_dir, contexts)
    shifted = copy.deepcopy(event)
    shifted["id"] = event["id"] + "-shifted"
    shifted["published_at"] = "2027-12-20T13:30:00+03:00"
    search = repository_search(FileRepository(fixtures / "bank-chunks.json"))
    record = run_pair(context, shifted, focus, search)
    result = record["envelope"]["result"]
    return {
        "name": "historical_bank",
        "description": "то же событие с датой 20.12.2027, материалы банка в корпусе старше года",
        "bank_view": result["bank_view"],
        "bank_view_context": result["bank_view_context"],
        "temporal_unknowns": [item for item in result["unknowns"] if "не показана как текущая" in item],
        "passed": result["bank_view"] is None and result["bank_view_context"]["status"] == "missing",
        "record": record,
    }


def additional_search(run_dir, contexts, fixtures=DEFAULT_FIXTURES) -> dict:
    context, event, focus = pick(run_dir, contexts)
    search = repository_search(FileRepository(fixtures / "bank-chunks.json"))
    record = run_pair(context, event, focus, search, suppressed=2)
    trace = record["envelope"]["trace"]
    return {
        "name": "additional_search",
        "description": "первые два поиска скрыты, агент обязан уточнить запрос",
        "extra_searches": trace.get("extra_searches"),
        "stop_reason": trace.get("stop_reason"),
        "queries": [call["query"] for call in record["searches"]],
        "passed": trace.get("extra_searches", 0) >= 1 and trace.get("extra_searches", 0) <= 2,
        "record": record,
    }


def corpus_change() -> dict:
    counter = {"runs": 0}

    def fake(company_context, user_focus, event, tools):
        counter["runs"] += 1
        return {"result": {}, "trace": {}}

    class Tools:
        def __init__(self, version):
            self.version = version

        def corpus_version(self):
            return self.version

    original = cache_calls.build_impact_insight
    cache_calls.build_impact_insight = fake
    try:
        cache = ResultCache()
        context = {"company_id": "B01", "profile_version": "p1"}
        event = {"id": "e1", "version": "v1"}
        focus = {"topics": ["x"], "priorities": []}
        cache_calls.cached_build_insight(context, focus, event, Tools("corpus-1"), cache)
        cache_calls.cached_build_insight(context, focus, event, Tools("corpus-1"), cache)
        cache_calls.cached_build_insight(context, focus, event, Tools("corpus-2"), cache)
    finally:
        cache_calls.build_impact_insight = original
    return {
        "name": "corpus_change",
        "description": "повтор с тем же корпусом берёт кеш, изменение версии корпуса вычисляет карточку заново",
        "computations": counter["runs"],
        "stats": cache.stats(),
        "passed": counter["runs"] == 2,
    }


def llm_failure(run_dir, contexts, fixtures=DEFAULT_FIXTURES) -> dict:
    context, event, focus = pick(run_dir, contexts)
    search = repository_search(FileRepository(fixtures / "bank-chunks.json"))
    keys = ("AI_LLM_API_KEY", "AI_LLM_BASE_URL", "AI_LLM_RETRY_BACKOFF_SECONDS", "AI_LLM_DAILY_LIMIT_RUB")
    saved = {key: os.environ.get(key) for key in keys}
    cases = [
        (
            "provider_unavailable",
            {**OFFLINE_ENV, "AI_LLM_BASE_URL": "http://127.0.0.1:9/v1", "AI_LLM_RETRY_BACKOFF_SECONDS": "0"},
        ),
        ("budget_exhausted", {**OFFLINE_ENV, "AI_LLM_DAILY_LIMIT_RUB": "0.000001"}),
    ]
    outcomes = []
    try:
        for name, env in cases:
            for key in keys:
                os.environ.pop(key, None)
            os.environ.update(env)
            get_llm_settings.cache_clear()
            shared_ledger.cache_clear()
            shared_transport.cache_clear()
            try:
                record = run_pair(context, event, focus, search)
                outcomes.append(
                    {"case": name, "code": record.get("error"), "card_returned": record["status"] == "ok"}
                )
            except LLMError as error:
                outcomes.append({"case": name, "code": error.code, "card_returned": False})
    finally:
        for key, value in saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value
        get_llm_settings.cache_clear()
        shared_ledger.cache_clear()
        shared_transport.cache_clear()
    return {
        "name": "llm_failure",
        "description": "недоступная модель и исчерпанный бюджет дают явную ошибку без карточки",
        "outcomes": outcomes,
        "passed": [item["code"] for item in outcomes] == ["provider_unavailable", "budget_exhausted"]
        and not any(item["card_returned"] for item in outcomes),
    }


def run_targeted(run_dir: Path, contexts: list[BenchmarkContext], live: bool = True) -> dict:
    results = {"corpus_change": corpus_change()}
    if live:
        results["historical_bank"] = historical_bank(run_dir, contexts)
        results["additional_search"] = additional_search(run_dir, contexts)
        results["llm_failure"] = llm_failure(run_dir, contexts)
    write(run_dir / "targeted.json", results)
    return results

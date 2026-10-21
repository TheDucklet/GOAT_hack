import json

import pytest

from app.ai.agent import runner as runner_module
from app.ai.agent import steps as steps_module
from app.ai.agent.runner import run_agent
from app.ai.agent.steps import fallback_queries, signature
from app.ai.insights import build as build_module
from app.ai.insights.build import prepare_insight
from app.ai.providers import LLMSettings, MemoryUsageSink, call_llm
from app.ai.providers.testing import completion, http_error, json_completion
from app.integrations.ai import AIError
from app.schemas import AIEnvelope, InsightResult
from tests.test_ai_insights import FOCUS, GOOD, company, event, hit


class Router:
    def __init__(self, plan=None, query=None, verify=None, insight=None):
        self.plan = (
            plan
            if plan is not None
            else {
                "needs": ["факты события", "признаки компании", "поиск по банку"],
                "queries": ["ключевая ставка кредитование", "инфляция ожидания"],
            }
        )
        self.query = (
            query
            if query is not None
            else [{"query": "денежно-кредитная политика строительство", "reason": "другие термины"}]
        )
        self.verify = verify
        self.insight = insight if insight is not None else [GOOD]
        self.calls = {"plan": 0, "query": 0, "verify": 0, "insight": 0}
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        system = request.system
        if "планируешь анализ" in system:
            kind, source = "plan", [self.plan]
        elif "уточняешь поисковый запрос" in system:
            kind, source = "query", self.query
        elif "проверяешь, подтверждают ли" in system:
            kind, source = "verify", self.verify or [self._supported(request)]
        else:
            kind, source = "insight", self.insight
        index = min(self.calls[kind], len(source) - 1)
        self.calls[kind] += 1
        answer = source[index]
        if isinstance(answer, str):
            return completion(answer)
        return json_completion(answer)

    @staticmethod
    def _supported(request):
        claims = json.loads(request.user)["claims"]
        return {
            "verdicts": [{"claim": item["claim"], "verdict": "supported", "reason": "ok"} for item in claims]
        }


class Search:
    def __init__(self, by_query=None, default=None):
        self.by_query = by_query or {}
        self.default = default if default is not None else []
        self.queries = []

    def __call__(self, query, as_of, limit):
        self.queries.append(query)
        items = self.by_query.get(query, self.default)
        return {"items": items, "query": query, "as_of": as_of, "empty_reason": None if items else "нет"}


class Tools:
    def __init__(self, context, search):
        self.context = context
        self.search = search

    def get_company_context(self, company_id=None):
        return self.context

    def get_event(self):
        return {}

    def search_bank_analytics(self, query, as_of, limit=5):
        return self.search(query, as_of, limit)


def llm_settings():
    return LLMSettings(_env_file=None, llm_api_key="sk-test", llm_retry_backoff_seconds=0)


def run(monkeypatch, router, search, ctx=None, payload=None, **kwargs):
    def patched(task, input, max_tokens, **options):
        return call_llm(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=router,
            usage_sink=MemoryUsageSink(),
            sleep=lambda seconds: None,
            **options,
        )

    monkeypatch.setattr(build_module, "call_llm", patched)
    monkeypatch.setattr(steps_module, "call_llm", patched)
    ctx = ctx or company()
    tools = Tools(ctx, search)
    return run_agent(ctx, FOCUS, payload or event(), tools, **kwargs), tools


def steps_of(envelope, key):
    return [step for step in envelope["trace"]["steps"] if key in step]


def test_ordinary_scenario_finishes_in_one_iteration(monkeypatch):
    router = Router()
    search = Search(default=[hit()])
    envelope, _ = run(monkeypatch, router, search)
    trace = envelope["trace"]
    assert trace["stop_reason"] == "supported"
    assert (trace["iterations"], trace["extra_searches"]) == (1, 0)
    assert len(search.queries) == 2
    assert envelope["result"]["bank_view"]


def test_trace_contains_plan_tools_evidence_ids_and_check(monkeypatch):
    envelope, _ = run(monkeypatch, Router(), Search(default=[hit()]))
    trace = envelope["trace"]
    plan_step = steps_of(envelope, "plan")[0]
    assert plan_step["initial_queries"] == ["ключевая ставка кредитование", "инфляция ожидания"]
    searches = steps_of(envelope, "tool") and [
        step for step in trace["steps"] if step.get("tool") == "search_bank_analytics"
    ]
    assert searches and searches[0]["evidence_ids"] and searches[0]["purpose"] == "initial"
    check_step = steps_of(envelope, "check")[0]
    assert check_step["check"] == "supported" and check_step["evidence_ids"]
    assert steps_of(envelope, "stop")[0]["stop"] == "supported"
    assert trace["checks"][0]["claims"]


def test_missing_first_evidence_triggers_a_new_search_with_a_different_query(monkeypatch):
    router = Router()
    search = Search(by_query={"денежно-кредитная политика строительство": [hit()]})
    envelope, _ = run(monkeypatch, router, search)
    trace = envelope["trace"]
    assert (trace["iterations"], trace["extra_searches"]) == (2, 1)
    assert trace["stop_reason"] == "supported"
    retry = steps_of(envelope, "retry")[0]
    assert retry["new_query"] == "денежно-кредитная политика строительство"
    assert retry["new_query"] not in retry["previous_queries"]
    assert retry["reason"] and retry["after_check"] == "insufficient"
    assert [check["status"] for check in trace["checks"]] == ["insufficient", "supported"]
    assert envelope["result"]["bank_view"]


def test_two_failed_retries_stop_without_a_third_search_and_without_confident_bank_claim(monkeypatch):
    router = Router(
        query=[
            {"query": "первый уточнённый запрос", "reason": "r1"},
            {"query": "второй уточнённый запрос", "reason": "r2"},
            {"query": "третий уточнённый запрос", "reason": "r3"},
        ]
    )
    search = Search(default=[])
    envelope, _ = run(monkeypatch, router, search)
    trace = envelope["trace"]
    assert trace["stop_reason"] == "retry_limit_reached"
    assert trace["extra_searches"] == 2
    assert len(search.queries) == 4
    assert "третий уточнённый запрос" not in search.queries
    result = envelope["result"]
    assert result["bank_view"] is None
    assert any("после 2 уточняющих поисков" in item for item in result["unknowns"])
    assert steps_of(envelope, "stop")[0]["stop"] == "retry_limit_reached"


def test_retry_limit_can_be_changed_and_zero_means_no_retries(monkeypatch):
    envelope, _ = run(monkeypatch, Router(), Search(default=[]), max_extra_searches=0)
    assert envelope["trace"]["extra_searches"] == 0
    assert envelope["trace"]["stop_reason"] == "retry_limit_reached"


def test_repeated_query_from_the_model_is_replaced_by_a_different_one(monkeypatch):
    router = Router(query=[{"query": "ключевая ставка кредитование", "reason": "тот же запрос"}])
    search = Search(default=[])
    envelope, _ = run(monkeypatch, router, search, max_extra_searches=1)
    new_query = steps_of(envelope, "retry")[0]["new_query"]
    assert signature(new_query) != signature("ключевая ставка кредитование")
    assert signature(new_query) != signature("инфляция ожидания")


def test_contradicting_bank_claim_is_removed_and_triggers_a_new_search(monkeypatch):
    verdicts = [
        {"verdicts": [{"claim": 1, "verdict": "contradiction", "reason": "в тексте другая ставка"}]},
        {"verdicts": [{"claim": 1, "verdict": "supported", "reason": "ok"}]},
    ]
    router = Router(verify=verdicts)
    other = hit("c2", page=2, text="Мы ожидаем сохранения ключевой ставки на уровне 14,0% до конца года")
    search = Search(by_query={"денежно-кредитная политика строительство": [other]}, default=[hit()])
    envelope, _ = run(monkeypatch, router, search)
    trace = envelope["trace"]
    assert trace["checks"][0]["status"] == "contradiction"
    assert trace["checks"][0]["rejected_bank_claims"][0]["verdict"] == "contradiction"
    assert trace["extra_searches"] == 1 and trace["stop_reason"] == "supported"


def test_historical_only_material_is_reported_and_retried(monkeypatch):
    search = Search(default=[hit(historical=True)])
    envelope, _ = run(monkeypatch, Router(), search, max_extra_searches=1)
    reasons = [item["code"] for item in envelope["trace"]["checks"][0]["reasons"]]
    assert reasons == ["only_historical"]
    assert envelope["result"]["bank_view"] is None


def test_event_without_facts_stops_immediately_without_search_or_llm(monkeypatch):
    router = Router()
    search = Search(default=[hit()])
    payload = event(facts=False) | {"evidence": []}
    envelope, _ = run(monkeypatch, router, search, payload=payload)
    assert envelope["trace"]["stop_reason"] == "no_event_facts"
    assert search.queries == [] and sum(router.calls.values()) == 0


def test_planner_failure_falls_back_to_event_queries(monkeypatch):
    router = Router(plan="не JSON")
    search = Search(default=[hit()])
    envelope, _ = run(monkeypatch, router, search)
    assert envelope["trace"]["stop_reason"] == "supported"
    assert search.queries[0] == event()["title"]


def test_missing_interpretation_stops_without_pointless_searches(monkeypatch):
    bad = {
        **GOOD,
        "ai_interpretation": [{"text": "Общий текст без признака компании.", "evidence_ids": ["N1"]}],
    }
    router = Router(insight=[bad, bad])
    search = Search(default=[hit()])
    envelope, _ = run(monkeypatch, router, search)
    assert envelope["trace"]["stop_reason"] == "no_further_search_possible"
    assert envelope["trace"]["extra_searches"] == 0


def test_retry_without_new_fragments_does_not_recompose_the_card(monkeypatch):
    router = Router(
        query=[{"query": "новый запрос один", "reason": "r"}, {"query": "новый запрос два", "reason": "r"}]
    )
    search = Search(default=[])
    run(monkeypatch, router, search)
    assert router.calls["insight"] == 1


def test_agent_does_not_search_another_company(monkeypatch):
    ctx = company("U_1")
    tools = Tools(company("U_2"), Search())
    with pytest.raises(AIError) as raised:
        prepare_insight(ctx, FOCUS, event(), tools)
    assert raised.value.code == "forbidden"


def test_result_is_valid_for_backend_schemas(monkeypatch):
    envelope, _ = run(monkeypatch, Router(), Search(default=[hit()]))
    AIEnvelope.model_validate(envelope)
    InsightResult.model_validate(envelope["result"])


def test_budget_exhaustion_is_not_swallowed_by_the_agent(monkeypatch):
    router = Router()
    original = router.send

    def failing(request):
        if "уточняешь поисковый запрос" in request.system:
            return http_error(400, "Budget has been exceeded")
        return original(request)

    router.send = failing
    with pytest.raises(AIError) as raised:
        run(monkeypatch, router, Search(default=[]))
    assert raised.value.code == "budget_exhausted"


def test_fallback_queries_use_other_terms_of_event_and_industry():
    ctx = company()
    prepared = prepare_insight(ctx, FOCUS, event(), Tools(ctx, Search()))
    queries = fallback_queries(prepared)
    assert queries and len({signature(item) for item in queries}) == len(queries)


def test_agent_run_uses_only_declared_tool_names(monkeypatch):
    envelope, _ = run(monkeypatch, Router(), Search(default=[hit()]))
    tools = {step["tool"] for step in envelope["trace"]["steps"] if "tool" in step}
    assert tools == {"get_company_context", "get_event", "search_bank_analytics"}


def test_module_constants_match_the_task():
    assert runner_module.MAX_EXTRA_SEARCHES == 2


def test_bridge_exposes_the_agent_as_build_insight(monkeypatch):
    from app.ai import bridge

    def patched(task, input, max_tokens, **options):
        return call_llm(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=Router(),
            usage_sink=MemoryUsageSink(),
            sleep=lambda seconds: None,
            **options,
        )

    monkeypatch.setattr(build_module, "call_llm", patched)
    monkeypatch.setattr(steps_module, "call_llm", patched)
    ctx = company()
    envelope = bridge.build_insight(ctx, FOCUS, event(), Tools(ctx, Search(default=[hit()])))
    assert envelope["trace"]["agent_version"] == "agent-2"
    assert {
        "build_insight",
        "derive_user_focus",
        "summarize_event",
        "search_bank_analytics",
        "ingest_bank_document",
    } <= set(bridge.__all__)


def test_verifier_receives_event_title_and_is_told_to_reject_unrelated_claims(monkeypatch):
    router = Router()
    run(monkeypatch, router, Search(default=[hit()]))
    request = next(item for item in router.requests if "проверяешь, подтверждают ли" in item.system)
    assert json.loads(request.user)["event_title"]
    assert "не относится к событию" in request.system

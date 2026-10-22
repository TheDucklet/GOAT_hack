import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from app.ai.agent import steps as steps_module
from app.ai.cache import ResultCache
from app.ai.cache import calls as calls_module
from app.ai.cache.calls import cached_build_insight
from app.ai.impact import build_impact_insight
from app.ai.impact import generate as impact_module
from app.ai.impact.assemble import bank_context, relevance_window
from app.ai.impact.dates import dates_in, grounded_date, parse_iso
from app.ai.impact.models import RawImpact
from app.ai.impact.prompts import IMPACT_SYSTEM_PROMPT
from app.ai.impact.rubric import assess, family_of
from app.ai.impact.scenario import ConfirmedInput, build_scenario
from app.ai.insights import build as build_module
from app.ai.providers import MemoryUsageSink, call_llm
from app.ai.providers.testing import ScriptedTransport, completion, json_completion
from app.ai.schemas import InsightEnvelopeV2
from app.notice_policy import DISCLAIMER, POLICY_VERSION
from app.schemas import AIEnvelope, InsightResultV2, parse_insight_result
from tests.test_ai_agent import FOCUS as _FOCUS  # noqa: F401
from tests.test_ai_agent import Router, Search, Tools, llm_settings
from tests.test_ai_insights import FOCUS, event, hit

EXAMPLES = json.loads(
    (
        Path(__file__).resolve().parents[2] / "docs" / "contracts" / "company-context-v2-examples.json"
    ).read_text(encoding="utf-8")
)
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
IMPACT_MARK = "строишь проверяемый механизм влияния"


def context(name):
    return next(item["data"] for item in EXAMPLES if item["name"] == name)


def pick(payload, needle):
    for item in payload["company_features"]:
        if needle in item["text"]:
            return item["id"]
    return None


def statement(text, *ids):
    return {"text": text, "evidence_ids": [item for item in ids if item]}


def credit_response(payload, level="medium", horizon=None, **overrides):
    loan = pick(payload, "кредиты")
    industry = pick(payload, "Основной вид деятельности")
    refs = ["N1", loan or industry]
    answer = {
        "summary": statement(
            "Сохранение ставки может удерживать расходы компании на обслуживание кредитов.", *refs
        ),
        "mechanism": [
            statement(
                "Если ставка остаётся на прежнем уровне, расходы на кредиты могут не снижаться при условии плавающей ставки.",
                *refs,
            )
        ],
        "impact_level": level,
        "impact_reason": statement("Канал подтверждён признаком продукта, масштаб долга неизвестен.", *refs),
        "horizon": horizon
        or {"kind": "unknown", "label": "Срок не назван", "starts_on": None, "ends_on": None},
        "assumptions": [statement("Вывод верен, если ставка по кредитам плавающая.", *refs)],
        "relevance_reason": statement("Вывод стоит перепроверить после уточнения условий кредитов.", *refs),
        "unknowns": ["Сумма долга компании"],
    }
    answer.update(overrides)
    return answer


class ImpactRouter(Router):
    def __init__(self, impact=None, **kwargs):
        super().__init__(**kwargs)
        self.impact = impact or credit_response
        self.calls["impact"] = 0
        self.impact_requests = []

    def send(self, request):
        if IMPACT_MARK in request.system:
            self.requests.append(request)
            self.impact_requests.append(request)
            self.calls["impact"] += 1
            payload = json.loads(request.user)
            answer = self.impact(payload) if callable(self.impact) else self.impact
            return completion(answer) if isinstance(answer, str) else json_completion(answer)
        return super().send(request)


def make(monkeypatch, router, ctx, search=None, payload=None, focus=None, now=NOW):
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

    for module in (build_module, steps_module, impact_module):
        monkeypatch.setattr(module, "call_llm", patched)
    tools = Tools(ctx, search or Search(default=[hit()]))
    return build_impact_insight(ctx, focus or FOCUS, payload or event(), tools, now)


def dated_event(text="Решение вступит в силу 23 октября 2026 года."):
    payload = event()
    payload["publications"][0]["text"] = "Ставка сохранена на уровне 14% годовых. " + text
    payload["evidence"][0]["excerpt"] = payload["publications"][0]["text"]
    return payload


def test_credit_company_gets_valid_v2_with_full_evidence_catalog(monkeypatch):
    envelope = make(monkeypatch, ImpactRouter(), context("u-client"))
    result = envelope["result"]
    InsightEnvelopeV2.model_validate(envelope)
    assert result["schema_version"] == "v2" and result["impact_level"] == "medium"
    kinds = {item["kind"] for item in envelope["evidence"]}
    assert kinds == {"news", "company", "bank"}
    assert set(result["evidence_refs"]) == {item["id"] for item in envelope["evidence"]}
    assert result["policy_version"] == POLICY_VERSION and result["disclaimer"] == DISCLAIMER
    assert envelope["trace"]["schema_version"] == "v2" and envelope["trace"]["impact"]["level"] == "medium"


def test_worker_boundary_accepts_the_generated_card(monkeypatch):
    envelope = make(monkeypatch, ImpactRouter(), context("u-client"))
    parsed = parse_insight_result(AIEnvelope.model_validate(envelope).result)
    assert isinstance(parsed, InsightResultV2)


def test_every_mechanism_step_cites_event_and_company_evidence(monkeypatch):
    envelope = make(monkeypatch, ImpactRouter(), context("u-client"))
    evidence = {item["id"]: item["kind"] for item in envelope["evidence"]}
    steps = envelope["result"]["mechanism"]
    assert steps
    for step in steps:
        kinds = {evidence[ref] for ref in step["evidence_refs"]}
        assert {"news", "company"} <= kinds and step["statement_type"] == "hypothesis"


def test_facts_and_bank_view_are_facts_and_analysis_is_hypothesis(monkeypatch):
    result = make(monkeypatch, ImpactRouter(), context("u-client"))["result"]
    assert {item["statement_type"] for item in result["facts"] + result["bank_view"]} == {"fact"}
    for key in ("ai_interpretation", "risks", "opportunities", "actions", "assumptions"):
        assert all(item["statement_type"] == "hypothesis" for item in result[key])


def test_prompt_states_explicitly_that_a_non_credit_company_has_no_bank_credit_product(monkeypatch):
    router = ImpactRouter()
    make(monkeypatch, router, context("u-prospect"))
    payload = json.loads(router.impact_requests[0].user)
    loan = next(item["text"] for item in payload["company_features"] if "кредиты" in item["text"])
    assert "продукта банка" in loan and "нет" in loan


def test_credit_and_non_credit_company_get_different_mechanisms(monkeypatch):
    def by_profile(payload):
        loan_text = next((i["text"] for i in payload["company_features"] if "кредиты" in i["text"]), "")
        if "да, у компании есть продукт" in loan_text:
            return credit_response(payload)
        industry = pick(payload, "Основной вид деятельности")
        answer = credit_response(payload)
        answer["mechanism"] = [
            statement(
                "Если ставка остаётся высокой, спрос покупателей компании может снижаться при условии зависимости от кредитов.",
                "N1",
                industry,
            )
        ]
        return answer

    with_credit = make(monkeypatch, ImpactRouter(impact=by_profile), context("u-client"))
    without = make(monkeypatch, ImpactRouter(impact=by_profile), context("u-prospect"))
    assert with_credit["result"]["mechanism"][0]["text"] != without["result"]["mechanism"][0]["text"]
    refs_with = {i["locator"].get("feature_path") for i in with_credit["evidence"] if i["kind"] == "company"}
    refs_without = {i["locator"].get("feature_path") for i in without["evidence"] if i["kind"] == "company"}
    assert refs_with != refs_without


def test_unconfirmed_profile_is_not_turned_into_credit_or_no_credit(monkeypatch):
    router = ImpactRouter(impact=lambda payload: credit_response(payload, level="undetermined"))
    envelope = make(monkeypatch, router, context("u-mixed"))
    result = envelope["result"]
    assert result["impact_level"] == "undetermined"
    assert result["personalized_summary"] is None and result["mechanism"] == []
    assert any("не определена" in item for item in result["unknowns"])
    assert any(
        "Наличие кредитного продукта банка в профиле не подтверждено" in item for item in result["unknowns"]
    )
    payload = json.loads(router.impact_requests[0].user)
    assert payload["company_features"] == []


def test_model_cannot_cite_a_label_that_does_not_exist(monkeypatch):
    def invented(payload):
        answer = credit_response(payload)
        answer["mechanism"][0]["evidence_ids"] = ["N1", "C99"]
        return answer

    envelope = make(monkeypatch, ImpactRouter(impact=invented), context("u-client"))
    impact = envelope["trace"]["impact"]
    assert envelope["result"]["impact_level"] == "undetermined"
    assert any(item["claim_id"] == "mechanism-1" for item in impact["dropped_statements"])


def test_mechanism_without_company_evidence_is_dropped(monkeypatch):
    def only_news(payload):
        answer = credit_response(payload)
        answer["mechanism"][0]["evidence_ids"] = ["N1"]
        return answer

    envelope = make(monkeypatch, ImpactRouter(impact=only_news), context("u-client"))
    assert envelope["result"]["mechanism"] == [] and envelope["result"]["impact_level"] == "undetermined"
    dropped = envelope["trace"]["impact"]["dropped_statements"]
    assert any(
        "missing_event_or_company" in item["reasons"] or "missing_premise" in item["reasons"]
        for item in dropped
    )


def test_invented_number_in_summary_is_replaced_by_a_verified_mechanism_step(monkeypatch):
    def numbers(payload):
        answer = credit_response(payload)
        answer["summary"]["text"] = "Расходы компании вырастут на 17 млн руб. при сохранении ставки."
        return answer

    envelope = make(monkeypatch, ImpactRouter(impact=numbers), context("u-client"))
    result = envelope["result"]
    assert "17" not in result["personalized_summary"]["text"]
    assert result["personalized_summary"]["text"].startswith("Если ставка остаётся")
    impact = envelope["trace"]["impact"]
    assert "summary" in impact["synthesized"]
    assert any("number_without_source" in item["reasons"] for item in impact["dropped_statements"])


def test_missing_impact_reason_is_written_by_the_rubric_not_invented(monkeypatch):
    router = ImpactRouter(impact=lambda payload: credit_response(payload, impact_reason=None))
    envelope = make(monkeypatch, router, context("u-client"))
    reason = envelope["result"]["impact_reason"]
    assert "по рубрике" in reason["text"] and "не вероятность" in reason["text"]
    assert reason["evidence_refs"] and "impact_reason" in envelope["trace"]["impact"]["synthesized"]


def test_unknown_strength_is_undetermined_not_low(monkeypatch):
    router = ImpactRouter(impact=lambda payload: credit_response(payload, level="undetermined"))
    result = make(monkeypatch, router, context("u-client"))["result"]
    assert result["impact_level"] == "undetermined"
    assert result["relevance_status"] == "undetermined" and result["relevance_reason"] is None
    assert result["next_actions"][0]["action"] == "ask_question"


def test_high_is_capped_to_medium_without_quantified_exposure(monkeypatch):
    envelope = make(
        monkeypatch,
        ImpactRouter(impact=lambda payload: credit_response(payload, level="high")),
        context("u-client"),
    )
    impact = envelope["trace"]["impact"]
    assert envelope["result"]["impact_level"] == "medium" and impact["proposed_level"] == "high"
    assert "exposure_not_quantified" in impact["caps"]
    assert any("не подтверждён числами" in item for item in envelope["result"]["unknowns"])


def test_model_failure_degrades_to_undetermined_instead_of_failing_the_card(monkeypatch):
    router = ImpactRouter(impact="это не JSON")
    result = make(monkeypatch, router, context("u-client"))["result"]
    assert result["impact_level"] == "undetermined" and result["facts"]
    assert any("модель не вернула разбираемый ответ" in item for item in result["unknowns"])


def test_budget_exhaustion_is_not_swallowed(monkeypatch):
    from app.ai.providers import LLMError

    def refuse(task, input, max_tokens, **options):
        if task == "build_impact":
            raise LLMError("budget_exhausted", "r1")
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

    for module in (build_module, steps_module, impact_module):
        monkeypatch.setattr(module, "call_llm", refuse)
    ctx = context("u-client")
    with pytest.raises(LLMError):
        build_impact_insight(ctx, FOCUS, event(), Tools(ctx, Search(default=[hit()])), NOW)


def test_event_without_facts_gives_an_undetermined_card_without_calling_the_impact_model(monkeypatch):
    router = ImpactRouter()
    payload = event(facts=False)
    payload["evidence"] = []
    envelope = make(monkeypatch, router, context("u-client"), payload=payload)
    assert router.calls["impact"] == 0
    assert envelope["result"]["impact_level"] == "undetermined"
    assert any("нет проверенных фактов" in item for item in envelope["result"]["unknowns"])


def test_missing_bank_view_keeps_external_analysis(monkeypatch):
    envelope = make(monkeypatch, ImpactRouter(), context("u-client"), search=Search(default=[]))
    result = envelope["result"]
    assert result["bank_view"] is None and result["bank_view_context"] == {
        "status": "missing",
        "document_dates": [],
    }
    assert result["impact_level"] == "medium" and result["mechanism"]


def test_bank_view_context_carries_document_dates(monkeypatch):
    result = make(monkeypatch, ImpactRouter(), context("u-client"))["result"]
    assert result["bank_view_context"] == {"status": "current", "document_dates": ["2026-09-11"]}


def test_undated_bank_material_is_not_shown_as_current_position(monkeypatch):
    undated = hit(date_unknown=True)
    envelope = make(monkeypatch, ImpactRouter(), context("u-client"), search=Search(default=[undated]))
    result = envelope["result"]
    assert result["bank_view"] is None
    assert any("stale_bank_position" in item for item in result["unknowns"])
    assert any("Нет подтверждающих материалов банка" in item for item in result["unknowns"])


def test_dated_horizon_sets_validity_and_review(monkeypatch):
    horizon = {"kind": "dated", "label": "До 23 октября 2026", "starts_on": None, "ends_on": "2026-10-23"}
    router = ImpactRouter(impact=lambda payload: credit_response(payload, horizon=horizon))
    result = make(monkeypatch, router, context("u-client"), payload=dated_event())["result"]
    assert result["time_horizon"]["ends_on"] == "2026-10-23"
    assert (result["relevance_status"], result["valid_until"], result["review_after"]) == (
        "active",
        "2026-10-23",
        "2026-10-23",
    )
    assert result["valid_from"] == "2026-09-11"


def test_invented_horizon_date_is_ignored(monkeypatch):
    horizon = {"kind": "dated", "label": "До 5 декабря", "starts_on": None, "ends_on": "2026-12-05"}
    router = ImpactRouter(impact=lambda payload: credit_response(payload, horizon=horizon))
    result = make(monkeypatch, router, context("u-client"), payload=dated_event())["result"]
    assert result["time_horizon"]["ends_on"] is None
    assert result["relevance_status"] == "undetermined"
    assert any("Срок актуальности" in item for item in result["unknowns"])


def test_expired_and_review_statuses_follow_the_clock(monkeypatch):
    horizon = {"kind": "dated", "label": "До 23 октября 2026", "starts_on": None, "ends_on": "2026-10-23"}
    router = ImpactRouter(impact=lambda payload: credit_response(payload, horizon=horizon))
    ctx = context("u-client")
    late = make(monkeypatch, router, ctx, payload=dated_event(), now=datetime(2026, 10, 24, 12, tzinfo=UTC))
    assert late["result"]["relevance_status"] == "expired"
    day = make(monkeypatch, router, ctx, payload=dated_event(), now=datetime(2026, 10, 23, 12, tzinfo=UTC))
    assert day["result"]["relevance_status"] == "review_required"


def test_long_term_effect_stays_active_long_after_publication(monkeypatch):
    horizon = {"kind": "long_term", "label": "Долгосрочный эффект", "starts_on": None, "ends_on": None}
    router = ImpactRouter(impact=lambda payload: credit_response(payload, horizon=horizon))
    result = make(monkeypatch, router, context("u-client"), now=datetime(2027, 6, 1, 12, tzinfo=UTC))[
        "result"
    ]
    assert result["relevance_status"] == "active" and result["valid_until"] is None


def test_published_date_is_not_used_as_validity_end(monkeypatch):
    result = make(monkeypatch, ImpactRouter(), context("u-client"))["result"]
    assert result["valid_until"] is None and result["time_horizon"]["ends_on"] is None


def test_prompt_carries_focus_so_roles_can_differ(monkeypatch):
    router = ImpactRouter()
    other = {**FOCUS, "priorities": ["управление ликвидностью"], "topics": ["депозиты и ликвидность"]}
    make(monkeypatch, router, context("u-client"), focus=FOCUS)
    make(monkeypatch, router, context("u-client"), focus=other)
    first, second = (json.loads(r.user)["user_focus"] for r in router.impact_requests)
    assert first != second and second["priorities"] == ["управление ликвидностью"]


def test_role_specific_answers_produce_different_cards(monkeypatch):
    def by_role(payload):
        answer = credit_response(payload)
        if "ликвидностью" in json.dumps(payload["user_focus"], ensure_ascii=False):
            deposit = pick(payload, "депозит") or pick(payload, "Основной вид деятельности")
            answer["mechanism"] = [
                statement(
                    "Если ставка остаётся высокой, доходность размещения свободных средств может сохраняться.",
                    "N1",
                    deposit,
                )
            ]
        return answer

    router = ImpactRouter(impact=by_role)
    ctx = context("u-client")
    base = make(monkeypatch, router, ctx, focus=FOCUS)["result"]["mechanism"][0]["text"]
    other = {**FOCUS, "priorities": ["управление ликвидностью"], "topics": ["депозиты и ликвидность"]}
    liquidity = make(monkeypatch, router, ctx, focus=other)["result"]["mechanism"]
    assert not liquidity or liquidity[0]["text"] != base


def test_relationships_are_reported_as_unknown_not_used_as_supplier_or_owner(monkeypatch):
    result = make(monkeypatch, ImpactRouter(), context("u-client"))["result"]
    assert any("смысл (поставка, кредит, владение) не установлен" in item for item in result["unknowns"])
    assert "поставщик" not in json.dumps(result, ensure_ascii=False).lower()


def test_prompt_contains_no_company_or_user_identifiers(monkeypatch):
    router = ImpactRouter()
    make(monkeypatch, router, context("u-client"))
    user = router.impact_requests[0].user
    assert "u-client" not in user and "profile_version" not in user


def test_prompt_forbids_known_semantic_traps():
    for fragment in (
        "Запись ФТС",
        "код группы",
        "ключевого собственника",
        "выручку без единицы",
        "undetermined",
    ):
        assert fragment in IMPACT_SYSTEM_PROMPT


def test_next_actions_come_from_the_allowlist_only(monkeypatch):
    result = make(monkeypatch, ImpactRouter(), context("u-client"))["result"]
    assert [item["action"] for item in result["next_actions"]] == [
        "ask_question",
        "contact_manager_demo",
        "hide_insight",
    ]


def test_model_output_cannot_override_policy_or_actions(monkeypatch):
    def hostile(payload):
        answer = credit_response(payload)
        answer["disclaimer"] = "ничего не нужно"
        answer["next_actions"] = [{"action": "run_tool", "command": "rm"}]
        answer["policy_version"] = "none"
        return answer

    result = make(monkeypatch, ImpactRouter(impact=hostile), context("u-client"))["result"]
    assert result["disclaimer"] == DISCLAIMER and result["policy_version"] == POLICY_VERSION
    assert all(item["action"] != "run_tool" for item in result["next_actions"])


def test_cache_reuses_the_same_card_and_counts_one_model_call(monkeypatch):
    router = ImpactRouter()
    ctx = context("u-client")
    monkeypatch.setattr(
        impact_module,
        "call_llm",
        lambda *a, **k: call_llm(
            *a,
            settings=llm_settings(),
            transport=router,
            usage_sink=MemoryUsageSink(),
            sleep=lambda s: None,
            **k,
        ),
    )
    for module in (build_module, steps_module):
        monkeypatch.setattr(
            module,
            "call_llm",
            lambda *a, **k: call_llm(
                *a,
                settings=llm_settings(),
                transport=router,
                usage_sink=MemoryUsageSink(),
                sleep=lambda s: None,
                **k,
            ),
        )

    class CorpusTools(Tools):
        def corpus_version(self):
            return "corpus-1"

    cache = ResultCache()
    tools = CorpusTools(ctx, Search(default=[hit()]))
    first = cached_build_insight(ctx, FOCUS, event(), tools, cache)
    calls = dict(router.calls)
    second = cached_build_insight(ctx, FOCUS, event(), tools, cache)
    assert router.calls == calls and second["result"] == first["result"]
    assert second["trace"]["cache"]["hit"] is True


def test_changed_impact_prompt_or_schema_version_gives_a_new_cache_identity(monkeypatch):
    ctx = context("u-client")
    seen = []
    monkeypatch.setattr(
        calls_module, "build_impact_insight", lambda *a: seen.append(1) or {"result": {}, "trace": {}}
    )

    class CorpusTools(Tools):
        def corpus_version(self):
            return "corpus-1"

    cache = ResultCache()
    tools = CorpusTools(ctx, Search(default=[]))
    cached_build_insight(ctx, FOCUS, event(), tools, cache)
    cached_build_insight(ctx, FOCUS, event(), tools, cache)
    monkeypatch.setattr(calls_module, "IMPACT_PROMPT_VERSION", "impact-99")
    cached_build_insight(ctx, FOCUS, event(), tools, cache)
    monkeypatch.setattr(
        calls_module, "contract_versions", lambda semantics=None: {"schema": "v3", "semantics": semantics}
    )
    cached_build_insight(ctx, FOCUS, event(), tools, cache)
    assert len(seen) == 3


def test_raw_impact_accepts_loose_model_output():
    raw = RawImpact.model_validate(
        {
            "summary": "Текст",
            "mechanism": "строка",
            "assumptions": ["а"],
            "horizon": "позже",
            "impact_level": None,
        }
    )
    assert (
        raw.summary.text == "Текст" and raw.horizon.kind == "unknown" and raw.impact_level == "undetermined"
    )
    assert raw.assumptions[0].text == "а"


def test_dates_are_found_in_russian_dotted_and_iso_forms():
    found = dates_in("23 октября 2026 года, 05.11.2026 и 2026-12-01, ошибочная 31.02.2026")
    assert found == {date(2026, 10, 23), date(2026, 11, 5), date(2026, 12, 1)}
    assert grounded_date("2026-10-23", "до 23 октября 2026") == date(2026, 10, 23)
    assert grounded_date("2026-10-24", "до 23 октября 2026") is None
    assert parse_iso("не дата") is None and parse_iso(None) is None


def test_bank_context_marks_old_documents_as_historical():
    evidence = {"b1": {"locator": {"document_date": "2026-03-01"}}}
    claims = [{"evidence_refs": ["b1"]}]
    assert bank_context(claims, evidence, date(2026, 9, 11))["status"] == "historical"
    assert bank_context(None, evidence, date(2026, 9, 11)) == {"status": "missing", "document_dates": []}


def test_relevance_window_rules():
    event_day, today = date(2026, 9, 11), date(2026, 10, 1)
    long_term = relevance_window("long_term", None, None, event_day, today, True)
    assert long_term["relevance_status"] == "active" and long_term["valid_until"] is None
    unknown = relevance_window("unknown", None, None, event_day, today, True)
    assert unknown["relevance_status"] == "undetermined"
    not_determined = relevance_window("long_term", None, None, event_day, today, False)
    assert not_determined["relevance_status"] == "undetermined"
    only_start_in_past = relevance_window("dated", date(2026, 9, 5), None, event_day, today, True)
    assert only_start_in_past["relevance_status"] == "active" and only_start_in_past["review_after"] is None
    future_start = relevance_window("dated", date(2026, 11, 1), None, event_day, today, True)
    assert future_start["review_after"] == date(2026, 11, 1) and future_start["relevance_status"] == "active"


def test_rubric_never_raises_the_level_and_requires_evidence():
    context_with_unit = {"features": {"REVENUE_COMPANY": {"unit": "RUB", "period": "2025"}}}
    matches = [{"factor": "product", "feature": "CL_PRODUCT_LOA_MARK", "value": "1"}]
    assert assess("undetermined", {}, set(), True, [], False, False).level == "undetermined"
    assert assess("medium", {}, set(), True, matches, False, False).level == "undetermined"
    assert assess("medium", {}, {"CL_PRODUCT_LOA_MARK"}, False, matches, False, False).level == "undetermined"
    assert assess("medium", {}, {"REGION"}, True, [], False, False).level == "undetermined"
    assert assess("medium", {}, {"CL_PRODUCT_LOA_MARK"}, True, matches, False, False).level == "medium"
    assert assess("medium", {}, {"REGION"}, True, [], True, False).level == "undetermined"
    assert assess("low", {}, {"REGION"}, True, [], False, False).level == "low"
    capped = assess("low", {}, {"CL_PRODUCT_LOA_MARK"}, True, matches, False, False)
    assert capped.level == "undetermined" and capped.caps == ["low_contradicts_direct_link"]
    assert assess("high", {}, {"CL_PRODUCT_LOA_MARK"}, True, matches, False, True).level == "medium"
    strong = assess(
        "high",
        context_with_unit,
        {"CL_PRODUCT_LOA_MARK", "REVENUE_COMPANY"},
        True,
        matches,
        True,
        True,
    )
    assert strong.level == "high" and strong.caps == []
    assert assess("surprise", {}, {"REGION"}, True, matches, True, True).level == "undetermined"


def test_features_are_grouped_into_independent_families():
    assert family_of("CL_PRODUCT_LOA_MARK") == family_of("FACTORING_MARK") == "product"
    assert family_of("MAINOKVED_NAME") == family_of("MAINOKVED_CODE") == "industry"
    assert family_of("ORG_TYPE") == "profile"


def confirmed(name, value, low, high, unit="RUB", period="year-2025", refs=("ref",)):
    return ConfirmedInput(name, value, low, high, unit, period, refs)


def test_scenario_is_built_only_from_complete_confirmed_inputs():
    debt, rate = (
        confirmed("debt", 100.0, 90.0, 110.0),
        confirmed("rate_change", 0.02, 0.01, 0.03, "share", "year"),
    )
    scenario = build_scenario("product", debt, rate, "RUB", "year", ["ставка применяется ко всему долгу"])
    assert scenario["result_range"]["lower"] == pytest.approx(0.9)
    assert scenario["result_range"]["upper"] == pytest.approx(3.3)
    assert scenario["formula"] == "result = factor_a * factor_b"
    assert build_scenario("eval('1+1')", debt, rate, "RUB", "year", ["a"]) is None
    assert build_scenario("product", debt, rate, "RUB", "year", []) is None
    assert (
        build_scenario(
            "product", debt, confirmed("rate_change", 0.02, 0.01, 0.03, "", "year"), "RUB", "year", ["a"]
        )
        is None
    )
    assert build_scenario("product", debt, confirmed("x", float("nan"), 0, 1), "RUB", "year", ["a"]) is None
    assert build_scenario("product", debt, debt, "RUB", "year", ["a"]) is None
    assert build_scenario("ratio", debt, confirmed("zero", 0.0, 0.0, 0.0), "share", "year", ["a"]) is None


def test_ratio_scenario_range_uses_interval_bounds():
    left, right = confirmed("part", 10.0, 8.0, 12.0), confirmed("whole", 100.0, 80.0, 120.0)
    scenario = build_scenario("ratio", left, right, "share", "year-2025", ["доли сопоставимы"])
    assert scenario["result_range"]["lower"] == pytest.approx(8 / 120)
    assert scenario["result_range"]["upper"] == pytest.approx(12 / 80)


def test_scripted_transport_is_not_used_by_other_modules():
    assert ScriptedTransport().calls == 0


def test_field_names_and_labels_are_removed_from_statement_text():
    text = "Влияет на денежные потоки (user_focus), как отмечено в N1 (company_features: C2)."
    cleaned = impact_module.clean_text(text)
    assert "user_focus" not in cleaned and "company_features" not in cleaned and "N1" not in cleaned
    assert "денежные потоки" in cleaned


def test_client_type_is_not_offered_to_the_impact_model(monkeypatch):
    router = ImpactRouter()
    make(monkeypatch, router, context("u-client"))
    texts = [item["text"] for item in json.loads(router.impact_requests[0].user)["company_features"]]
    assert not any("Тип клиента банка" in text for text in texts)


def test_committed_examples_are_valid_v2_envelopes_with_application_policy():
    path = Path(__file__).resolve().parents[2] / "docs" / "ai" / "impact-examples.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert {case["name"] for case in cases} >= {"credit_company_accountant", "unconfirmed_profile_accountant"}
    for case in cases:
        envelope = InsightEnvelopeV2.model_validate(case["envelope"])
        assert envelope.result.disclaimer == DISCLAIMER and envelope.result.policy_version == POLICY_VERSION
        assert envelope.result.next_actions[0].action == "ask_question"
    unknown = next(c for c in cases if c["name"] == "unconfirmed_profile_accountant")["envelope"]["result"]
    assert unknown["impact_level"] == "undetermined" and unknown["mechanism"] == []

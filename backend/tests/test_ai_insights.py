import json

import pytest

from app.ai.insights import build as build_module
from app.ai.insights.build import build_insight
from app.ai.insights.context import (
    company_facts,
    evidence_id,
    matched_features,
    readable_money,
    readable_value,
)
from app.ai.providers import LLMSettings, MemoryUsageSink, call_llm
from app.ai.providers.testing import ScriptedTransport, completion, json_completion
from app.integrations.ai import AIError
from app.schemas import AIEnvelope, InsightResult


def feature(value):
    return {"value": value, "source": {"file": "df_Uid_data_hack.csv", "field": "x"}}


def company(company_id="U_1", loan="1.0", deposit="1.0", revenue="3609087410.0"):
    return {
        "company_id": company_id,
        "profile_version": "csv-1",
        "group_id": None,
        "features": {
            "MAINOKVED_NAME": feature("Строительство жилых и нежилых зданий"),
            "REGION": feature("Москва"),
            "REVENUE_COMPANY": feature(revenue),
            "CL_PRODUCT_LOA_MARK": feature(loan),
            "CL_PRODUCT_DEP_MARK": feature(deposit),
            "FTS_COUNTRY_NAME": feature(""),
        },
        "unknowns": ["FTS_COUNTRY_NAME"],
        "payment_links": {"outgoing": [], "incoming": []},
        "related_companies": [],
    }


def event(facts=True, topics=None):
    return {
        "id": "event-1",
        "title": "Банк России сохранил ключевую ставку на уровне 14%",
        "summary": "Ставка осталась на уровне 14% годовых.",
        "published_at": "2026-09-11T16:30:00+03:00",
        "version": "v1",
        "topics": topics
        if topics is not None
        else {
            "theme": ["ключевая ставка"],
            "industry": [],
            "product": ["CL_PRODUCT_LOA_MARK"],
            "geo": [],
            "relation": [],
        },
        "facts": [
            {
                "claim_id": "fact-1",
                "text": "Ставка сохранена на уровне 14% годовых.",
                "evidence_refs": ["ev-news-1"],
            }
        ]
        if facts
        else None,
        "publications": [
            {"id": "pub-1", "url": "https://example.org/n", "text": "Ставка сохранена на уровне 14% годовых."}
        ],
        "evidence": [
            {
                "id": "ev-news-1",
                "kind": "news",
                "source_id": "pub-1",
                "version": "hash",
                "locator": {"url": "https://example.org/n"},
                "excerpt": "Ставка сохранена на уровне 14% годовых.",
            }
        ],
    }


FOCUS = {
    "topics": ["бюджет и налоги"],
    "priorities": ["оценка стоимости заимствований"],
    "unknowns": [],
    "version": "focus-1",
}


def hit(
    chunk_id="c1",
    page=1,
    historical=False,
    date_unknown=False,
    text="Мы ожидаем сохранения ставки на уровне 14,0% до конца года",
):
    return {
        "chunk_id": chunk_id,
        "document_id": "doc-1",
        "version": "v1",
        "index_version": "i1",
        "page": page,
        "document_date": None if date_unknown else "2026-09-11",
        "date_unknown": date_unknown,
        "historical": historical,
        "text": text,
        "excerpt": text,
        "locator": {"page": page},
        "score": 9.5,
    }


class FakeTools:
    def __init__(self, context, hits=(), event_payload=None):
        self.context = context
        self.hits = list(hits)
        self.queries = []

    def get_company_context(self, company_id=None):
        return self.context

    def get_event(self):
        return {}

    def search_bank_analytics(self, query, as_of, limit=5):
        self.queries.append((query, as_of, limit))
        return {
            "items": self.hits,
            "query": query,
            "as_of": as_of,
            "empty_reason": None if self.hits else "нет",
        }


def llm_settings():
    return LLMSettings(_env_file=None, llm_api_key="sk-test", llm_retry_backoff_seconds=0)


def run(monkeypatch, answer, ctx=None, hits=(), payload=None, extra_answers=()):
    transport = ScriptedTransport(json_completion(answer), *[json_completion(item) for item in extra_answers])

    def patched(task, input, max_tokens, **kwargs):
        return call_llm(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=transport,
            usage_sink=MemoryUsageSink(),
            sleep=lambda seconds: None,
            **kwargs,
        )

    monkeypatch.setattr(build_module, "call_llm", patched)
    ctx = ctx or company()
    tools = FakeTools(ctx, hits)
    return build_insight(ctx, FOCUS, payload or event(), tools), transport, tools


def claim(text, *ids):
    return {"text": text, "evidence_ids": list(ids)}


GOOD = {
    "bank_view": [claim("Альфа-Банк ожидает сохранения ставки на уровне 14,0% до конца года.", "B1")],
    "ai_interpretation": [
        claim(
            "Высокая ставка 14% увеличивает стоимость обслуживания кредитов компании, у которой есть кредитный продукт.",
            "N1",
            "C4",
        )
    ],
    "risks": [claim("Рост нагрузки по кредитам при ставке 14%.", "N1", "C4")],
    "opportunities": [claim("Рост дохода от депозитов.", "N1", "C5")],
    "actions": [claim("Проверить тип ставки по действующим кредитам.", "C4")],
    "unknowns": ["Сумма долга компании."],
}


def aliases_of(ctx=None):
    facts = company_facts(ctx or company())
    return {f.feature: f for f in facts}


def test_claim_refs_are_real_evidence_ids_and_only_new_evidence_is_returned(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    result = envelope["result"]
    assert result["facts"][0]["evidence_refs"] == ["ev-news-1"]
    assert result["ai_interpretation"][0]["evidence_refs"][0] == "ev-news-1"
    kinds = {item["kind"] for item in envelope["evidence"]}
    assert kinds == {"bank", "company"}
    assert all(item["id"] != "ev-news-1" for item in envelope["evidence"])
    assert set(result["evidence_refs"]) >= {item["id"] for item in envelope["evidence"]}


def test_result_is_valid_for_backend_schemas(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    AIEnvelope.model_validate(envelope)
    InsightResult.model_validate(envelope["result"])


def test_bank_view_cites_only_bank_evidence(monkeypatch):
    answer = {**GOOD, "bank_view": [claim("Банк ожидает сохранения ставки 14,0%.", "B1", "C4", "N1")]}
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    refs = envelope["result"]["bank_view"][0]["evidence_refs"]
    bank_ids = {item["id"] for item in envelope["evidence"] if item["kind"] == "bank"}
    assert set(refs) == bank_ids


def test_bank_view_without_bank_evidence_is_dropped(monkeypatch):
    answer = {**GOOD, "bank_view": [claim("Банк ожидает сохранения ставки 14,0%.", "C4")]}
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    assert envelope["result"]["bank_view"] is None
    assert any("банка" in item for item in envelope["result"]["unknowns"])


def test_no_bank_fragments_give_null_bank_view_and_explanation(monkeypatch):
    envelope, _, _ = run(monkeypatch, {**GOOD, "bank_view": []}, hits=[])
    result = envelope["result"]
    assert result["bank_view"] is None
    assert "Нет подтверждающих материалов банка на дату события" in result["unknowns"]


def test_historical_bank_material_is_not_used_as_current_position(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit(historical=True)])
    result = envelope["result"]
    assert result["bank_view"] is None
    assert any("исторические" in item for item in result["unknowns"])
    assert all(item["kind"] != "bank" for item in envelope["evidence"])


def test_bank_material_with_unknown_date_is_flagged_in_unknowns(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit(date_unknown=True)])
    assert any(
        "Дата использованного материала банка неизвестна" in item for item in envelope["result"]["unknowns"]
    )


def test_interpretation_needs_company_feature_and_premise(monkeypatch):
    answer = {
        **GOOD,
        "ai_interpretation": [claim("Ставка 14% важна для всех компаний без исключения.", "N1")],
    }
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()], extra_answers=[answer])
    assert envelope["result"]["ai_interpretation"] == []
    assert [item["reason"] for item in envelope["trace"]["dropped_claims"]] == [
        "missing_company_feature_or_premise"
    ]


def test_valid_second_attempt_replaces_an_invalid_first_one(monkeypatch):
    bad = {**GOOD, "ai_interpretation": [claim("Ставка 14% важна для всех компаний без исключения.", "N1")]}
    envelope, transport, _ = run(monkeypatch, bad, hits=[hit()], extra_answers=[GOOD])
    assert transport.calls == 2
    assert envelope["result"]["ai_interpretation"]
    assert envelope["trace"]["dropped_claims"] == []


def test_invalid_interpretation_is_retried_once_and_then_left_empty(monkeypatch):
    bad = {**GOOD, "ai_interpretation": [claim("Общий текст без признака компании.", "N1")]}
    envelope, transport, _ = run(monkeypatch, bad, hits=[hit()], extra_answers=[bad])
    assert transport.calls == 2
    assert envelope["result"]["ai_interpretation"] == []
    assert any(step.get("attempt") == 2 for step in envelope["trace"]["steps"])


def test_claim_with_number_absent_from_sources_is_dropped(monkeypatch):
    answer = {
        **GOOD,
        "risks": [
            claim("Потери составят 500 млн руб. в год.", "N1", "C4"),
            claim("Рост нагрузки при ставке 14%.", "N1", "C4"),
        ],
    }
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    texts = [item["text"] for item in envelope["result"]["risks"]]
    assert texts == ["Рост нагрузки при ставке 14%."]
    assert any(item["reason"] == "number_not_in_sources" for item in envelope["trace"]["dropped_claims"])


def test_unknown_evidence_ids_are_ignored(monkeypatch):
    answer = {**GOOD, "risks": [claim("Рост нагрузки.", "N99", "ZZ")]}
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    assert envelope["result"]["risks"] == []


def test_derived_sections_inherit_interpretation_evidence_when_model_gives_none(monkeypatch):
    answer = {**GOOD, "risks": [claim("Рост нагрузки при ставке 14%.")], "actions": ["Проверить тип ставки"]}
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    result = envelope["result"]
    assert result["risks"][0]["evidence_refs"] == result["ai_interpretation"][0]["evidence_refs"]
    assert result["actions"][0]["evidence_refs"]


def test_evidence_labels_are_removed_from_claim_text(monkeypatch):
    answer = {
        **GOOD,
        "ai_interpretation": [
            claim("Для строительной компании (C1) ставка 14% дорога (N1, C4).", "N1", "C4")
        ],
    }
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    text = envelope["result"]["ai_interpretation"][0]["text"]
    assert "(C1)" not in text and "N1" not in text and "C4" not in text


def test_model_may_return_a_single_object_or_strings(monkeypatch):
    answer = {
        **GOOD,
        "bank_view": claim("Банк ожидает сохранения ставки 14,0%.", "B1"),
        "actions": ["Проверить условия"],
    }
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    assert envelope["result"]["bank_view"]


def test_event_without_facts_makes_no_llm_call_and_reports_insufficient_data(monkeypatch):
    envelope, transport, _ = run(monkeypatch, GOOD, payload=event(facts=False) | {"evidence": []})
    result = envelope["result"]
    assert transport.calls == 0
    assert result["facts"] == [] and result["ai_interpretation"] == []
    assert any("недостаточно" in item for item in result["unknowns"])
    assert envelope["trace"]["stop_reason"] == "no_event_facts"


def test_tool_for_another_company_is_rejected(monkeypatch):
    ctx = company("U_1")
    tools = FakeTools(company("U_2"))
    with pytest.raises(AIError) as raised:
        build_insight(ctx, FOCUS, event(), tools)
    assert raised.value.code == "forbidden"


def test_loan_event_adds_domain_unknowns_for_company_with_loan(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    assert any("кредитов неизвестны" in item for item in envelope["result"]["unknowns"])


def test_loan_event_for_company_without_loan_asks_about_other_banks(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, ctx=company("U_2", loan="0.0"), hits=[hit()])
    assert any("других банках" in item for item in envelope["result"]["unknowns"])


def test_different_profiles_get_different_company_evidence(monkeypatch):
    first, _, _ = run(monkeypatch, GOOD, ctx=company("U_1", loan="1.0"), hits=[hit()])
    second, _, _ = run(monkeypatch, GOOD, ctx=company("U_2", loan="0.0"), hits=[hit()])
    first_texts = {item["excerpt"] for item in first["evidence"] if item["kind"] == "company"}
    second_texts = {item["excerpt"] for item in second["evidence"] if item["kind"] == "company"}
    assert first_texts != second_texts


def test_evidence_ids_are_stable_between_runs(monkeypatch):
    first, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    second, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    assert [item["id"] for item in first["evidence"]] == [item["id"] for item in second["evidence"]]


def test_company_evidence_matches_backend_snapshot_rules(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    for item in envelope["evidence"]:
        if item["kind"] == "company":
            assert item["source_id"] == "U_1" and item["version"] == "csv-1"
            assert item["locator"]["feature_path"].startswith("features.")
        if item["kind"] == "bank":
            assert item["locator"]["page"] >= 1


def test_trace_lists_tools_matches_and_model_usage(monkeypatch):
    envelope, _, tools = run(monkeypatch, GOOD, hits=[hit()])
    steps = envelope["trace"]["steps"]
    assert [step.get("tool") for step in steps if "tool" in step][:2] == ["get_company_context", "get_event"]
    assert any(step.get("tool") == "search_bank_analytics" for step in steps)
    assert any(step.get("llm") == "build_insight" and step["request_id"] for step in steps)
    assert envelope["trace"]["matched_with_event"] == [
        {"factor": "product", "feature": "CL_PRODUCT_LOA_MARK", "value": "1"}
    ]
    assert tools.queries and tools.queries[0][1] == "2026-09-11"


def test_news_text_in_prompt_is_not_mixed_with_instructions(monkeypatch):
    _, transport, _ = run(monkeypatch, GOOD, hits=[hit()])
    payload = json.loads(transport.requests[0].user)
    assert set(payload) >= {"event", "news", "company_features", "bank_fragments", "user_focus"}
    assert all(
        item["id"].startswith(("C", "B")) for item in payload["company_features"] + payload["bank_fragments"]
    )


def test_matched_features_cover_industry_geo_and_products():
    ctx = company()
    topics = {
        "industry": ["Строительство жилых и нежилых зданий"],
        "geo": ["Москва"],
        "product": ["CL_PRODUCT_LOA_MARK", "CL_PRODUCT_DEP_MARK"],
    }
    factors = [(item["factor"], item["feature"]) for item in matched_features(ctx, topics)]
    assert ("industry", "MAINOKVED_NAME") in factors and ("geo", "REGION") in factors
    assert ("product", "CL_PRODUCT_LOA_MARK") in factors
    assert matched_features(company(loan="0.0"), {"product": ["CL_PRODUCT_LOA_MARK"]}) == []


def test_money_and_flag_formatting_keep_both_exact_and_rounded_values():
    assert readable_money("3609087410.0") == "3 609 087 410 руб. (около 3,6 млрд руб.)"
    assert readable_money("388738862.0") == "388 738 862 руб. (около 388,7 млн руб.)"
    assert "нет" in readable_value("CL_PRODUCT_LOA_MARK", "0.0")
    assert "да" in readable_value("CL_PRODUCT_LOA_MARK", "1.0")


def test_missing_features_are_not_offered_as_evidence():
    features = {fact.feature for fact in company_facts(company())}
    assert "FTS_COUNTRY_NAME" not in features and "REGION" in features


def test_evidence_ids_depend_on_company_version_and_feature():
    assert evidence_id("U_1", "csv-1", "REGION") == evidence_id("U_1", "csv-1", "REGION")
    assert evidence_id("U_1", "csv-1", "REGION") != evidence_id("U_1", "csv-2", "REGION")
    assert evidence_id("U_1", "csv-1", "REGION") != evidence_id("U_2", "csv-1", "REGION")


def test_invalid_json_from_model_raises_typed_error(monkeypatch):
    transport = ScriptedTransport(completion("не JSON"))

    def patched(task, input, max_tokens, **kwargs):
        return call_llm(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=transport,
            usage_sink=MemoryUsageSink(),
            **kwargs,
        )

    monkeypatch.setattr(build_module, "call_llm", patched)
    with pytest.raises(AIError) as raised:
        build_insight(company(), FOCUS, event(), FakeTools(company(), [hit()]))
    assert raised.value.code == "invalid_json"

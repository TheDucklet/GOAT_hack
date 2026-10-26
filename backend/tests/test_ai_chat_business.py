import json

import pytest

from app.ai.insights.context import evidence_id
from app.publication_policy import NO_SOURCES_TEXT
from tests.test_ai_chat import Router, Search, ask
from tests.test_ai_insights import FOCUS, company, event


@pytest.mark.parametrize("loan", ["0.0", None])
def test_business_context_offers_confirmed_alternative_without_credit_exposure(monkeypatch, loan):
    context = company("business-context", loan=loan)
    if loan is None:
        del context["features"]["CL_PRODUCT_LOA_MARK"]
    router = Router()
    ask(monkeypatch, "Почему это важно?", ctx=context, router=router)
    payload = json.loads(router.requests[-1].user)
    aliases = {item["id"]: item["text"] for item in payload["company_features"]}
    bases = payload["mechanism_bases"]
    assert any("депозит" in item["text"].lower() for item in bases)
    assert all("кредит" not in item["text"].lower() for item in bases)
    assert all(aliases[item["id"]] == item["text"] for item in bases)
    assert payload["user_focus"]["priorities"] == FOCUS["priorities"]


def test_source_conditions_are_bound_to_the_news_even_if_summary_omits_them(monkeypatch):
    payload = event()
    condition = "Условие получения льготы — доля профильного дохода не менее 70%."
    payload["publications"][0]["text"] += " " + condition
    envelope, router, _ = ask(monkeypatch, "Применима ли мера?", payload=payload)
    inputs = json.loads(router.requests[-1].user)
    assert inputs["source_conditions"] == [{"evidence_id": "N1", "text": condition}]
    assert envelope["result"]


def test_validation_retry_explains_the_rejected_presupposition_and_keeps_the_sources(monkeypatch):
    context = company("repair", loan="0.0")
    bad = {
        "answer": "Компания снизит стоимость обслуживания существующих кредитов.",
        "evidence_ids": ["N1"],
        "unknowns": [],
    }
    good = {
        "answer": "Если у компании есть депозит с плавающей ставкой, то сохранение ключевой ставки может сохранить доходность по нему.",
        "evidence_ids": ["N1", "C5"],
        "unknowns": ["условия договора депозита"],
    }
    router = Router(route={"intent": "importance", "search_query": None}, answers=[bad, good])
    envelope, router, _ = ask(monkeypatch, "Почему это важно?", ctx=context, router=router, search=Search())
    assert router.calls["answer"] == 2
    prompts = [json.loads(item.user) for item in router.requests if "Ты помощник" in item.system]
    feedback = prompts[1]["validation_feedback"]
    assert feedback["reason"] == "validation_failed"
    assert any(item["code"] == "presupposed_product" for item in feedback["problems"])
    assert feedback["rejected_answer"] == bad["answer"]
    assert prompts[0]["news"] == prompts[1]["news"]
    assert prompts[0]["company_features"] == prompts[1]["company_features"]
    assert envelope["result"]["answer"] == good["answer"]
    assert evidence_id("repair", "csv-1", "CL_PRODUCT_DEP_MARK") in envelope["result"]["evidence_refs"]
    assert [a["reason"] for a in envelope["trace"]["validation_attempts"]] == ["validation_failed", None]


def test_failed_repair_remains_a_refusal_after_two_attempts(monkeypatch):
    bad = {
        "answer": "Компания снизит стоимость обслуживания существующих кредитов.",
        "evidence_ids": ["N1"],
        "unknowns": [],
    }
    router = Router(answers=[bad, bad])
    envelope, router, _ = ask(monkeypatch, "Почему это важно?", ctx=company(loan="0.0"), router=router)
    assert router.calls["answer"] == 2
    assert envelope["result"]["answer"] == NO_SOURCES_TEXT
    assert envelope["result"]["evidence_refs"] == []
    assert len(envelope["trace"]["validation_attempts"]) == 2


def test_structured_mechanism_uses_its_own_evidence_and_discards_unverified_free_text(monkeypatch):
    answer = {
        "answer": "Компания уже получила доход 700 млн рублей.",
        "evidence_ids": ["N77"],
        "mechanism": {
            "condition": "у компании есть депозит с плавающей ставкой",
            "consequence": "сохранение ключевой ставки может сохранить доходность по нему",
            "evidence_ids": ["N1", "C5"],
        },
        "unknowns": ["условия договора депозита"],
    }
    envelope, _, _ = ask(monkeypatch, "Почему это важно?", router=Router(answers=[answer]), search=Search())
    result = envelope["result"]
    assert (
        result["answer"]
        == "Если у компании есть депозит с плавающей ставкой, то сохранение ключевой ставки может сохранить доходность по нему."
    )
    assert "700" not in result["answer"] and "N77" not in result["evidence_refs"]
    assert "ev-news-1" in result["evidence_refs"]
    assert result["unknowns"]


def test_incomplete_mechanism_is_not_replaced_with_the_unchecked_free_text(monkeypatch):
    answer = {
        "answer": "Компания получит доход.",
        "evidence_ids": ["N1"],
        "mechanism": {"condition": "", "consequence": "доход может вырасти", "evidence_ids": ["N1"]},
    }
    envelope, router, _ = ask(monkeypatch, "Почему это важно?", router=Router(answers=[answer]))
    assert router.calls["answer"] == 2
    assert envelope["result"]["answer"] == NO_SOURCES_TEXT
    assert envelope["trace"]["validation_attempts"][0]["reason"] == "incomplete_conditional_mechanism"


@pytest.mark.parametrize(
    "condition,consequence,reason",
    [
        (
            "неизвестный объём средств на депозитах",
            "эффект может зависеть от остатков",
            "missing_applicability_condition",
        ),
        (
            "у компании есть депозит",
            "эффект может быть значительным или незначительным",
            "non_specific_consequence",
        ),
        (
            "у компании есть депозит",
            "доходность обязательно сохранится",
            "unqualified_conditional_consequence",
        ),
    ],
)
def test_vacuous_or_unqualified_mechanism_is_not_counted_as_a_business_answer(
    monkeypatch, condition, consequence, reason
):
    answer = {"mechanism": {"condition": condition, "consequence": consequence, "evidence_ids": ["N1", "C5"]}}
    envelope, router, _ = ask(monkeypatch, "Почему это важно?", router=Router(answers=[answer]))
    assert envelope["result"]["answer"] == NO_SOURCES_TEXT
    assert router.calls["answer"] == 2
    assert envelope["trace"]["validation_attempts"][0]["reason"] == reason

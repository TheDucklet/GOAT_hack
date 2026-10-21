import json
from pathlib import Path

import pytest

from app.ai.evaluation import checks as c
from app.ai.evaluation.__main__ import main
from app.ai.evaluation.pipeline import SearchLog, Workspace
from app.ai.evaluation.scenarios import Session, llm_failure
from app.ai.summarization.conflicts import quantities, similar_context, source_conflicts
from app.ai.summarization.grounding import shorten
from tests.test_ai_insights import GOOD, company, event, hit, run

ACCEPTANCE = Path(__file__).resolve().parents[2] / "docs" / "quality" / "acceptance"


def fact(claim_id, text, ref):
    return {"claim_id": claim_id, "text": text, "evidence_refs": [ref]}


HOUSING_ONE = "По данным Минстроя, в январе-августе 2026 года введено 68,4 млн кв. м жилья, что на 3% меньше, чем годом ранее."
HOUSING_TWO = "Издание сообщает, что за восемь месяцев 2026 года введено 66,9 млн кв. м жилья, что на 5% меньше, чем годом ранее."


def test_different_numbers_for_the_same_quantity_in_two_sources_are_a_conflict():
    notes = source_conflicts([fact("f1", HOUSING_ONE, "e1"), fact("f2", HOUSING_TWO, "e2")])
    assert len(notes) == 1 and notes[0].startswith("Источники события расходятся")


def test_same_values_or_one_source_are_not_a_conflict():
    same = HOUSING_TWO.replace("66,9", "68,4").replace("5%", "3%")
    assert source_conflicts([fact("f1", HOUSING_ONE, "e1"), fact("f2", same, "e2")]) == []
    assert source_conflicts([fact("f1", HOUSING_ONE, "e1"), fact("f2", HOUSING_TWO, "e1")]) == []


def test_unrelated_facts_with_the_same_unit_are_not_a_conflict():
    rate = "Совет директоров сохранил ключевую ставку на уровне 14% годовых."
    inflation = "Недельная инфляция замедлилась до 0,04% после роста цен на овощи."
    assert source_conflicts([fact("f1", rate, "e1"), fact("f2", inflation, "e2")]) == []
    assert not similar_context(rate, inflation)


def test_quantities_normalize_separators_and_skip_unknown_units():
    assert quantities("выручка 3 609 087 410 руб. и рост 3,5% к 15 сентября") == {
        "руб": {"3609087410"},
        "%": {"3.5"},
    }


def test_shorten_cuts_on_a_word_boundary():
    assert shorten("один два три четыре", 12) == "один два..."
    assert shorten("  один   два ", 30) == "один два"


def two_source_payload():
    payload = event()
    payload["facts"] = [
        fact("fact-1", HOUSING_ONE, "ev-news-1"),
        fact("fact-2", HOUSING_TWO, "ev-news-2"),
    ]
    payload["publications"] = [
        {"id": "pub-1", "url": "https://example.org/a", "text": HOUSING_ONE},
        {"id": "pub-2", "url": "https://example.org/b", "text": HOUSING_TWO},
    ]
    payload["evidence"] = [
        {
            "id": f"ev-news-{number}",
            "kind": "news",
            "source_id": f"pub-{number}",
            "version": f"hash-{number}",
            "locator": {"url": f"https://example.org/{'ab'[number - 1]}"},
            "excerpt": text,
        }
        for number, text in ((1, HOUSING_ONE), (2, HOUSING_TWO))
    ]
    return payload


def test_card_names_the_conflict_first_and_keeps_both_sources(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, payload=two_source_payload(), hits=[hit()])
    result = envelope["result"]
    assert result["unknowns"][0].startswith("Источники события расходятся")
    assert {ref for item in result["facts"] for ref in item["evidence_refs"]} == {"ev-news-1", "ev-news-2"}
    assert len(envelope["trace"]["source_conflicts"]) == 1


def test_card_without_conflict_has_empty_conflict_trace(monkeypatch):
    envelope, _, _ = run(monkeypatch, GOOD, hits=[hit()])
    assert envelope["trace"]["source_conflicts"] == []


def test_source_labels_are_removed_from_model_unknowns(monkeypatch):
    answer = {**GOOD, "unknowns": ["Сумма и условия кредитных договоров (C4, N1).", "Тип ставки [B1]"]}
    envelope, _, _ = run(monkeypatch, answer, hits=[hit()])
    unknowns = envelope["result"]["unknowns"]
    assert "Сумма и условия кредитных договоров." in unknowns and "Тип ставки" in unknowns
    assert not any("C4" in item or "B1" in item for item in unknowns)


def test_long_unknowns_are_shortened_without_cutting_a_word(monkeypatch):
    long_note = "слово " * 60
    envelope, _, _ = run(monkeypatch, {**GOOD, "unknowns": [long_note]}, hits=[hit()])
    note = next(item for item in envelope["result"]["unknowns"] if item.startswith("слово"))
    assert note.endswith("слово...") and len(note) <= 220


def sample_card():
    return {
        "result": {
            "facts": [fact("fact-1", "Ставка 14% годовых.", "ev-1")],
            "bank_view": None,
            "ai_interpretation": [fact("ai-1", "Ставка 14% важна.", "ev-1")],
            "risks": [],
            "opportunities": [],
            "actions": [],
            "unknowns": [],
        },
        "evidence": [],
        "trace": {"validation": {"claims": []}},
    }


def sample_event():
    return {
        "title": "Новость",
        "publications": [{"id": "p", "url": "u", "text": "Ставка 14% годовых."}],
        "evidence": [{"id": "ev-1", "kind": "news"}],
    }


def test_acceptance_checks_detect_unknown_refs_and_invented_numbers():
    card, source = sample_card(), sample_event()
    assert c.refs_resolve(card, source)["ok"]
    assert c.numbers_grounded(card, source, company())["ok"]
    card["result"]["risks"] = [fact("risk-1", "Потери составят 700 млн руб.", "ev-404")]
    assert not c.refs_resolve(card, source)["ok"]
    assert not c.numbers_grounded(card, source, company())["ok"]
    assert c.verdict_of([c.check("a", True), c.check("b", False)]) == "FAIL"


def test_bank_view_rule_rejects_non_bank_sources():
    card = sample_card()
    card["result"]["bank_view"] = [fact("bank-1", "Банк ожидает.", "ev-1")]
    card["evidence"] = [{"id": "ev-1", "kind": "company"}]
    assert not c.bank_view_rule(card)["ok"]


def test_retrieval_check_passes_on_the_committed_snapshot(tmp_path):
    assert main(["retrieval", "--output", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "retrieval.json").read_text(encoding="utf-8"))
    assert report["passed"] == report["total"] == 5


def test_search_log_hides_the_requested_number_of_first_searches():
    workspace = Workspace()
    log = SearchLog(workspace.search, suppressed=1)
    first = log("ключевая ставка", "2026-09-30", 5)
    second = log("ключевая ставка", "2026-09-30", 5)
    assert first["items"] == [] and second["items"]
    assert [call["suppressed"] for call in log.calls] == [True, False]


@pytest.mark.skipif(not (ACCEPTANCE / "S7.json").exists(), reason="результат приёмки не записан")
def test_saved_additional_search_replays_to_the_same_fragments():
    assert main(["search", "--scenario", "S7", "--output", str(ACCEPTANCE)]) == 0


@pytest.mark.skipif(not (ACCEPTANCE / "S1.json").exists(), reason="результат приёмки не записан")
def test_llm_failure_scenario_returns_explicit_errors_and_no_card(monkeypatch):
    monkeypatch.delenv("AI_LLM_API_KEY", raising=False)
    saved = json.loads((ACCEPTANCE / "S1.json").read_text(encoding="utf-8"))["cards"][0]
    session = Session(Workspace())
    session._events["inflation_weekly"] = (
        {
            **session.workspace.raw_event("inflation_weekly"),
            "summary": saved["summary"]["summary"],
            "facts": saved["summary"]["facts"],
            "topics": saved["summary"]["topics"],
        },
        saved["summary"],
    )
    session._focuses["chief_accountant"] = saved["focus"]
    result = llm_failure(session)
    assert result["verdict"] == "PASS"
    assert [item["code"] for item in result["outcomes"]] == ["provider_unavailable", "budget_exhausted"]


def test_contradiction_caught_by_validation_does_not_fail_the_published_card():
    card = sample_card()
    card["trace"]["validation"]["claims"] = [{"claim_id": "ai-gone", "verdict": "contradiction"}]
    assert c.validation_clean(card)["ok"]
    card["trace"]["validation"]["claims"] = [{"claim_id": "ai-1", "verdict": "contradiction"}]
    assert not c.validation_clean(card)["ok"]

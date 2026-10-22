import json
from datetime import date
from pathlib import Path

import pytest

from app.ai.rag.search import search_bank_analytics
from app.ai.rag.temporal import temporal_status
from app.ai.schemas import BankSearchResult
from app.ai.validation import CONTRADICTION, INSUFFICIENT, SUPPORTED, validate_answer
from app.ai.validation.__main__ import case_catalog, catalog_from, load, main, run_case
from tests.test_ai_chat import Router as ChatRouter
from tests.test_ai_chat import Search as ChatSearch
from tests.test_ai_chat import ask
from tests.test_ai_evaluation import two_source_payload
from tests.test_ai_insights import GOOD, claim, company, hit, run

FIXTURES = Path(__file__).resolve().parents[2] / "docs" / "ai" / "fixtures"
SEMANTIC = load(FIXTURES / "semantic-cases.json")
COMPANIES = {item["company_id"]: item for item in load(FIXTURES / "companies.json")}
CHUNKS = {item["chunk_id"]: item for item in load(FIXTURES / "bank-chunks.json")}
BASE = catalog_from(SEMANTIC, COMPANIES, CHUNKS)
CASES = {case["name"]: case for case in SEMANTIC["cases"]}


def judged(name):
    case = CASES[name]
    return run_case(case, case_catalog(BASE, case["state"]))


@pytest.mark.parametrize("name", list(CASES))
def test_semantic_case_gets_expected_verdict_and_codes(name):
    result = judged(name)
    assert result["matched"], result


def test_every_required_regression_has_a_blocking_fixture():
    required = {
        "S5_existing_credits_unknown_debt",
        "fts_without_direction",
        "city_name_is_not_plant_location",
        "self_payment_as_external_turnover",
        "group_id_as_ownership",
        "revenue_1000_unconfirmed",
        "payments_with_unconfirmed_2025",
    }
    assert required <= set(CASES)
    for name in required:
        assert judged(name)["verdict"] in {INSUFFICIENT, CONTRADICTION}, name


def test_correct_conclusions_keep_their_sources():
    for name in ("conditional_credit_hypothesis", "credit_product_confirmed", "current_bank_position"):
        result = judged(name)
        assert result["verdict"] == SUPPORTED
        assert result["kept_refs"] == CASES[name]["claim"]["evidence_refs"]


def test_false_bank_fact_is_not_hidden_behind_a_valid_source_id():
    result = judged("bank_opinion_without_bank_source")
    assert result["evidence_status"] and set(result["evidence_status"].values()) == {"valid"}
    assert result["verdict"] == INSUFFICIENT


def test_semantic_cli_writes_a_report_per_claim(tmp_path):
    output = tmp_path / "semantic.json"
    assert main(["semantic", "--fixtures", str(FIXTURES), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"]["cases"] == report["summary"]["matched"] == len(CASES)
    assert {item["claim"]["claim_id"] for item in report["cases"]} == set(CASES)


def test_chat_validation_rejects_the_same_presupposition_as_the_card():
    unknown = case_catalog(BASE, {"flags": {"CL_PRODUCT_LOA_MARK": "unknown"}})
    text = "Снижение ставки уменьшит стоимость обслуживания существующих кредитов компании."
    chat = validate_answer(text, ["ev-news-1"], [], unknown)
    assert chat["verdict"] == INSUFFICIENT
    assert any(item["code"] == "presupposed_product" for item in chat["record"]["reasons"])


def test_temporal_status_uses_content_not_one_cutoff_for_every_topic():
    as_of = date(2026, 9, 12)
    assert temporal_status("2026-08-20", "обзор рынка", as_of)[0] == "current"
    assert temporal_status("2026-02-01", "прогноз ставки на конец 2026 г.", as_of)[0] == "current"
    assert temporal_status("2026-02-01", "итоги 2025 г. и динамика цен", as_of)[0] == "period_expired"
    assert temporal_status("2026-02-01", "общий обзор без периодов", as_of)[0] == "applicability_unknown"
    assert temporal_status("2025-01-01", "прогноз на 2026 г.", as_of)[0] == "historical"
    assert temporal_status(None, "текст", as_of)[0] == "undated"


class MemoryRepository:
    def __init__(self, chunks):
        self.chunks = chunks

    def search_chunks(self, query, as_of, limit=5):
        return self.chunks


def chunk(document_date, text, chunk_id="c1", filename="Обзор рынка.pdf"):
    return {
        "chunk_id": chunk_id,
        "document_id": "d1",
        "version": "v1",
        "index_version": "i1",
        "filename": filename,
        "page": 3,
        "document_date": document_date,
        "text": text,
    }


def test_search_results_carry_title_page_version_date_and_temporal_status():
    repository = MemoryRepository([chunk("2026-09-01", "Ключевая ставка 14% годовых")])
    found = search_bank_analytics("ключевая ставка", "2026-09-12", 5, repository)
    item = found["items"][0]
    assert item["title"] == "Обзор рынка" and item["page"] == 3 and item["version"] == "v1"
    assert item["document_date"] == "2026-09-01" and item["temporal_status"] == "current"
    assert item["historical"] is False
    BankSearchResult.model_validate(found)


def test_search_marks_old_undated_and_expired_documents_as_not_current():
    repository = MemoryRepository(
        [
            chunk("2025-03-01", "Ключевая ставка в 2025 году", "c1"),
            chunk(None, "Ключевая ставка 14% годовых", "c2"),
            chunk("2026-02-01", "Ключевая ставка по итогам 2025 года", "c3"),
        ]
    )
    found = search_bank_analytics("ключевая ставка", "2026-09-12", 5, repository)
    statuses = {item["chunk_id"]: item["temporal_status"] for item in found["items"]}
    assert statuses == {"c1": "historical", "c2": "undated", "c3": "period_expired"}
    assert all(item["historical"] for item in found["items"])


def test_chat_names_the_old_material_and_does_not_present_it_as_current(monkeypatch):
    old = hit(historical=True)
    old.update(title="Обзор 2025", temporal_status="historical", temporal_reason="документ старше года")
    envelope, _, _ = ask(monkeypatch, "Что говорит банк о ставке?", search=ChatSearch([old]))
    unknowns = envelope["result"]["unknowns"]
    assert any("Обзор 2025" in item and "не показана как текущая" in item for item in unknowns)
    assert not [item for item in envelope["evidence"] if item["kind"] == "bank"]


def test_chat_reports_source_conflict_instead_of_choosing_a_side(monkeypatch):
    envelope, _, _ = ask(monkeypatch, "Сколько жилья введено?", payload=two_source_payload())
    result = envelope["result"]
    assert result["unknowns"][0].startswith("Источники события расходятся")
    assert "Источники события расходятся" in result["answer"]
    assert envelope["trace"]["source_conflicts"]


def test_chat_with_incomplete_profile_does_not_pass_a_credit_presupposition(monkeypatch):
    profile = company()
    profile["features"].pop("CL_PRODUCT_LOA_MARK")
    bad = {
        "answer": "Снижение ставки уменьшит стоимость обслуживания существующих кредитов компании.",
        "evidence_ids": ["N1", "C1"],
        "unknowns": [],
    }
    router = ChatRouter(answers=[bad, bad])
    envelope, router, _ = ask(monkeypatch, "Почему это важно нам?", router=router, ctx=profile)
    assert "кредитов компании" not in envelope["result"]["answer"]
    assert any("presupposed_product" in item for item in envelope["result"]["unknowns"])
    assert router.calls["answer"] == 2


def test_card_drops_a_presupposed_risk_for_unknown_debt(monkeypatch):
    profile = company()
    profile["features"].pop("CL_PRODUCT_LOA_MARK")
    answer = {
        **GOOD,
        "risks": [claim("Рост стоимости обслуживания существующих кредитов снизит прибыль.", "N1", "C1")],
    }
    envelope, _, _ = run(monkeypatch, answer, ctx=profile, hits=[hit()])
    assert all("существующих кредитов" not in item["text"] for item in envelope["result"]["risks"])
    assert any("presupposed_product" in item for item in envelope["result"]["unknowns"])


def test_working_capital_is_not_mistaken_for_turnover():
    from app.ai.validation.semantics import PAYMENT_TURNOVER

    assert not PAYMENT_TURNOVER.search("Платежи по кредитам зависят от оборотных средств компании.")
    assert PAYMENT_TURNOVER.search("Платежи компании составляют её оборот.")

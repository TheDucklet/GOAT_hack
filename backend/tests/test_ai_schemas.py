import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import schemas as backend_schemas
from app.ai import schemas as ai

EXAMPLES_PATH = Path(__file__).resolve().parents[2] / "docs/contracts/ai-examples.json"
EXAMPLES = {item["name"]: item for item in json.loads(EXAMPLES_PATH.read_text(encoding="utf-8"))}

BACKEND_RESULT_MODEL = {
    "InsightEnvelope": backend_schemas.AIEnvelope,
    "ChatEnvelope": backend_schemas.AIEnvelope,
    "GroundedSummaryResult": backend_schemas.SummaryResult,
    "GroundedUserFocus": backend_schemas.UserFocus,
    "GroundedIngestResult": backend_schemas.IngestResult,
}


def example(name):
    return copy.deepcopy(EXAMPLES[name]["data"])


def test_required_examples_are_published():
    assert {"insight_card", "insight_without_bank_view", "insight_insufficient_data"} <= set(EXAMPLES)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_validates_against_ai_schema_without_changes(name):
    item = EXAMPLES[name]
    getattr(ai, item["schema"]).model_validate(item["data"])


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_is_accepted_by_backend_schemas(name):
    item = EXAMPLES[name]
    backend_model = BACKEND_RESULT_MODEL.get(item["schema"])
    if backend_model is None:
        pytest.skip("no backend counterpart")
    backend_model.model_validate(item["data"])


@pytest.mark.parametrize("name", ["insight_card", "insight_without_bank_view", "insight_insufficient_data"])
def test_insight_result_is_accepted_by_backend_insight_schema(name):
    backend_schemas.InsightResult.model_validate(example(name)["result"])


def test_chat_result_is_accepted_by_backend_chat_schema():
    backend_schemas.ChatResult.model_validate(example("chat_answer")["result"])


def test_function_contracts_cover_all_ai_functions():
    assert set(ai.FUNCTION_CONTRACTS) == {
        "derive_user_focus",
        "summarize_event",
        "ingest_bank_document",
        "search_bank_analytics",
        "build_insight",
        "answer_chat",
    }
    assert all(contract.errors for contract in ai.FUNCTION_CONTRACTS.values())


def test_every_evidence_in_examples_resolves_to_a_target():
    for name in ("insight_card", "chat_answer"):
        for item in example(name)["evidence"]:
            target = ai.evidence_target(ai.GroundedEvidence.model_validate(item))
            assert target.source_id == item["source_id"]


def test_news_evidence_targets_original_url():
    news = ai.GroundedEvidence.model_validate(example("insight_card")["evidence"][0])
    assert ai.evidence_target(news).href == news.locator["url"]


def test_bank_evidence_targets_pdf_page_counted_from_one():
    bank = ai.GroundedEvidence.model_validate(example("insight_card")["evidence"][1])
    assert ai.evidence_target(bank).page == 1


def test_bank_evidence_with_page_zero_is_rejected():
    data = example("insight_card")
    data["evidence"][1]["locator"]["page"] = 0
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_news_evidence_without_url_is_rejected():
    data = example("insight_card")
    data["evidence"][0]["locator"] = {}
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_company_evidence_requires_feature_path_prefix():
    data = example("insight_card")
    data["evidence"][2]["locator"] = {"feature_path": "CL_PRODUCT_LOA_MARK"}
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_claim_without_evidence_is_rejected():
    data = example("insight_card")
    data["result"]["facts"][0]["evidence_refs"] = []
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_duplicate_claim_id_across_sections_is_rejected():
    data = example("insight_card")
    data["result"]["risks"][0]["claim_id"] = "fact-1"
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_empty_bank_view_list_is_rejected():
    data = example("insight_card")
    data["result"]["bank_view"] = []
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_missing_bank_view_requires_explanation_in_unknowns():
    data = example("insight_without_bank_view")
    data["result"]["unknowns"] = []
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_bank_view_citing_news_evidence_is_rejected():
    data = example("insight_card")
    data["result"]["bank_view"][0]["evidence_refs"] = ["example-news-evidence"]
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_top_level_evidence_refs_must_match_claims():
    data = example("insight_card")
    data["result"]["evidence_refs"].append("example-company-evidence-extra")
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_insight_without_facts_requires_unknowns():
    data = example("insight_insufficient_data")
    data["result"]["unknowns"] = []
    with pytest.raises(ValidationError):
        ai.InsightEnvelope.model_validate(data)


def test_chat_answer_without_evidence_requires_unknowns():
    data = example("chat_insufficient_data")
    data["result"]["unknowns"] = []
    with pytest.raises(ValidationError):
        ai.ChatEnvelope.model_validate(data)


def test_empty_search_result_requires_reason():
    data = example("bank_search_empty")
    data["empty_reason"] = None
    with pytest.raises(ValidationError):
        ai.BankSearchResult.model_validate(data)


def test_search_result_is_limited_to_five_items():
    data = example("bank_search_result")
    data["items"] = data["items"] * 6
    with pytest.raises(ValidationError):
        ai.BankSearchResult.model_validate(data)


def test_search_hit_with_unknown_date_must_be_flagged():
    data = example("bank_search_result")
    data["items"][0]["document_date"] = None
    with pytest.raises(ValidationError):
        ai.BankSearchResult.model_validate(data)


def test_ingest_chunk_with_blank_text_is_rejected():
    data = example("ingest_result")
    data["chunks"][0]["text"] = "   "
    with pytest.raises(ValidationError):
        ai.GroundedIngestResult.model_validate(data)


def test_ingest_document_date_must_be_iso():
    data = example("ingest_result")
    data["document_date"] = "11.09.2026"
    with pytest.raises(ValidationError):
        ai.GroundedIngestResult.model_validate(data)


def test_arbitrary_position_text_is_accepted_by_focus_input():
    for position in [
        "Главный бухгалтер",
        "Директор по закупкам",
        "Руководитель направления тендерного сопровождения",
        "",
    ]:
        assert ai.DeriveUserFocusInput(position_text=position, interests=[]).position_text == position


def test_failure_marks_only_transient_codes_as_retryable():
    assert ai.AIFailure.of("timeout", "x").retryable
    assert ai.AIFailure.of("rate_limited", "x").retryable
    assert ai.AIFailure.of("provider_unavailable", "x").retryable
    assert not ai.AIFailure.of("budget_exhausted", "x").retryable
    assert not ai.AIFailure.of("invalid_json", "x").retryable

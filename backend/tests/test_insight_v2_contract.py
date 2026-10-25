"""Shared F-13 fixtures plus adversarial boundaries; no LLM calls."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from app import insight_versions
from app.ai.schemas import InsightEnvelopeV2
from app.insight_provenance import validate_v2_provenance
from app.notice_policy import notice_policy
from app.schemas import AIEnvelope, InsightOut, InsightResult, InsightResultV2, parse_insight_result

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "docs/contracts"
FIXTURES = json.loads((CONTRACTS / "insight-v2-examples.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda item: item["name"])
def test_shared_fixture_crosses_ai_worker_and_http_without_losing_fields(fixture):
    envelope = InsightEnvelopeV2.model_validate(fixture["envelope"])
    worker = AIEnvelope.model_validate(envelope.model_dump(mode="json"))
    result = parse_insight_result(worker.result)
    validate_v2_provenance(result, worker.evidence)
    http = InsightOut(id="insight", company_id="DEMO_ONLY", event_id="event", versions={}, result=result)
    assert http.result.model_dump(mode="json", exclude_none=True) == result.model_dump(
        mode="json", exclude_none=True
    )
    assert isinstance(http.result, InsightResultV2)


def test_original_v1_examples_are_unchanged_tagless_and_readable():
    examples = json.loads((CONTRACTS / "examples.json").read_text(encoding="utf-8"))
    for example in examples:
        if example["schema"] == "InsightResult":
            result = parse_insight_result(example["data"])
            assert type(result) is InsightResult
            assert result.model_dump(mode="json") == example["data"]


@pytest.mark.parametrize(
    "patch",
    [
        {"schema_version": "v3"},
        {"schema_version": "v1"},
        {"policy_version": "notice_v2"},
        {"disclaimer": "LLM removed the notice"},
        {"impact_reason": None},
        {"mechanism": []},
        {"evidence_refs": []},
        {"bank_view": []},
        {"unknowns": []},
        {"valid_until": "2020-01-01"},
        {"review_after": "2020-01-01"},
        {"valid_until": "2026-10-25"},
        {"valid_from": None},
        {"next_actions": [{"action": "execute_tool", "label": "run", "command": "anything"}]},
        {"next_actions": [{"action": "ask_question", "label": "ask"}]},
        {"next_actions": [{"action": "hide_insight", "label": "hide", "question": "run?"}]},
    ],
)
def test_invalid_v2_cannot_downgrade_to_v1(patch):
    result = {**copy.deepcopy(FIXTURES[0]["envelope"]["result"]), **patch}
    with pytest.raises(ValidationError):
        parse_insight_result(result)
    with pytest.raises(ValidationError):
        InsightOut(id="i", company_id="c", event_id="e", versions={}, result=result)


@pytest.mark.parametrize("field", ["formula", "inputs", "unit", "period", "assumptions", "result_range"])
def test_quantitative_scenario_requires_full_calculation_metadata(field):
    envelope = copy.deepcopy(FIXTURES[-1]["envelope"])
    del envelope["result"]["risks"][0]["quantitative_scenario"][field]
    with pytest.raises(ValidationError):
        InsightEnvelopeV2.model_validate(envelope)


@pytest.mark.parametrize(
    "mutation", ["input_refs", "range", "statement_type", "nonfinite", "duplicate_input"]
)
def test_bad_scenario_is_rejected(mutation):
    envelope = copy.deepcopy(FIXTURES[-1]["envelope"])
    claim = envelope["result"]["risks"][0]
    scenario = claim["quantitative_scenario"]
    if mutation == "input_refs":
        scenario["inputs"][0]["input_refs"] = ["unknown-evidence"]
    elif mutation == "range":
        scenario["result_range"] = {"lower": 100, "upper": 1}
    elif mutation == "statement_type":
        claim["statement_type"] = "fact"
    elif mutation == "duplicate_input":
        scenario["inputs"].append(scenario["inputs"][0])
    else:
        scenario["inputs"][0]["value"] = float("inf")
    with pytest.raises(ValidationError):
        InsightEnvelopeV2.model_validate(envelope)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_evidence",
        "wrong_bank_kind",
        "wrong_bank_date",
        "undated_bank",
        "empty_grounding",
        "duplicate_claim",
        "hypothesis_as_fact",
    ],
)
def test_provenance_and_attribution_fail_closed(mutation):
    envelope = copy.deepcopy(FIXTURES[2]["envelope"])
    if mutation == "missing_evidence":
        envelope["evidence"].pop()
    elif mutation == "wrong_bank_kind":
        envelope["result"]["bank_view"][0]["evidence_refs"] = ["news-rate"]
    elif mutation == "wrong_bank_date":
        envelope["result"]["bank_view_context"]["document_dates"] = ["2026-10-22"]
    elif mutation == "undated_bank":
        del envelope["evidence"][-1]["locator"]["document_date"]
    elif mutation == "empty_grounding":
        envelope["result"]["personalized_summary"]["evidence_refs"] = []
    elif mutation == "duplicate_claim":
        envelope["result"]["mechanism"][0]["claim_id"] = "event"
    else:
        envelope["result"]["facts"][0]["statement_type"] = "hypothesis"
    with pytest.raises(ValidationError):
        InsightEnvelopeV2.model_validate(envelope)


def test_policy_defaults_are_injected_by_application():
    result = copy.deepcopy(FIXTURES[0]["envelope"]["result"])
    del result["policy_version"], result["disclaimer"]
    parsed = parse_insight_result(result).model_dump()
    assert {key: parsed[key] for key in notice_policy()} == notice_policy()


def test_generated_schemas_and_policy_have_no_manual_drift():
    expected = {
        "insight.schema.json": TypeAdapter(InsightResultV2 | InsightResult).json_schema(),
        "insight-envelope-v2.schema.json": InsightEnvelopeV2.model_json_schema(),
        "notice-policy.json": notice_policy(),
    }
    for name, value in expected.items():
        assert json.loads((CONTRACTS / name).read_text(encoding="utf-8")) == value


def test_undetermined_is_not_an_unexplained_low_impact():
    result = copy.deepcopy(FIXTURES[1]["envelope"]["result"])
    result["impact_level"] = "low"
    with pytest.raises(ValidationError):
        parse_insight_result(result)


@pytest.mark.parametrize(
    "name", ["INSIGHT_CONTRACT_VERSION", "INSIGHT_SCHEMA_VERSION", "DATA_SEMANTICS_VERSION", "POLICY_VERSION"]
)
def test_contract_namespace_changes_on_each_version(monkeypatch, name):
    before = insight_versions.contract_versions()
    monkeypatch.setattr(insight_versions, name, "changed")
    assert insight_versions.contract_versions() != before


@pytest.mark.parametrize("complete_catalogue", [True, False])
def test_v2_worker_persistence_and_readback(client, monkeypatch, complete_catalogue):
    from app.services.jobs import run_one
    from tests import fake_ai
    from tests.factories import enable_ai, event_fixture, login

    enable_ai(monkeypatch)
    original = fake_ai.build_insight

    def v2_result(**kwargs):
        old = original(**kwargs)
        result = copy.deepcopy(FIXTURES[1]["envelope"]["result"])
        result.update(
            facts=[{**claim, "statement_type": "fact"} for claim in old["result"]["facts"]],
            evidence_refs=old["result"]["evidence_refs"],
            trace_id=old["result"]["trace_id"],
        )
        # Policy intentionally omitted: the application must supply it.
        del result["policy_version"], result["disclaimer"]
        envelope = {
            "result": result,
            "evidence": kwargs["event"]["evidence"] if complete_catalogue else [],
            "trace": {},
        }
        envelope["trace"] = fake_ai.allowed({**envelope, "result": dict(result)})["trace"]
        return envelope

    monkeypatch.setattr(fake_ai, "build_insight", v2_result)
    login(client)
    event_id = event_fixture()
    request = client.post("/companies/demo_company_a/insights", json={"event_id": event_id})
    assert request.status_code == 202
    assert run_one()
    status = client.get(f"/jobs/{request.json()['id']}").json()
    if not complete_catalogue:
        assert status["status"] == "failed"
        assert status["error"]["code"] == "invalid_evidence"
        return
    assert status["status"] == "done"
    response = client.get(f"/insights/{status['result']['insight_id']}")
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["schema_version"] == "v2"
    assert result["impact_level"] == "undetermined"
    assert {key: result[key] for key in notice_policy()} == notice_policy()
    for actual, expected in zip(
        result["next_actions"], FIXTURES[1]["envelope"]["result"]["next_actions"], strict=True
    ):
        assert actual == {"question": None, **expected}
    assert client.post("/companies/demo_company_a/insights", json={"event_id": event_id}).status_code == 200

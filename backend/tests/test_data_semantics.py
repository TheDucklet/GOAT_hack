"""A-14: real column names and adversarial synthetic data, never real LLM calls."""

import csv
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.ai.insights.context import company_facts
from app.ai.schemas import BuildInsightInput
from app.data_semantics import (
    COMPANIES_FILE,
    DATA_SEMANTICS_VERSION,
    PAYMENTS_FILE,
    PEOPLE_FILE,
    normalize_feature,
)
from app.db import session_factory
from app.models import ClientRawRow, Company, ImportBatch, Membership, Payment
from app.schemas import CompanyContextV2, DataFeature
from app.services import client_import
from app.services.clients import company_context, demo_candidates, import_clients
from tests.factories import login

FIXTURES = Path(__file__).parent / "fixtures/a14"


@pytest.fixture
def imported(env):
    for name in [COMPANIES_FILE, PEOPLE_FILE, PAYMENTS_FILE]:
        shutil.copyfile(FIXTURES / name, env / name)
    with session_factory()() as db, db.begin():
        report = import_clients(db, env)
    return env, report


@pytest.mark.parametrize(
    "raw,quality",
    [
        ("1000", "assumed"),
        ("1000.0", "assumed"),
        ("2000000", "assumed"),
        ("NaN", "missing"),
        ("-1", "invalid"),
        ("", "missing"),
    ],
)
def test_revenue_year_currency_and_placeholder_are_not_manufactured(raw, quality):
    entry = normalize_feature("REVENUE_COMPANY", [(2, {"REVENUE_COMPANY": raw})], "sha")
    assert entry["raw"] == [raw]
    assert entry["quality"] == quality and entry["value"] is None
    assert entry["unit"] is None and entry["period"] == "annual_year_unknown"
    DataFeature.model_validate(entry)


def test_uncertain_feature_cannot_become_a_confirmed_legacy_value():
    entry = normalize_feature("REVENUE_COMPANY", [(2, {"REVENUE_COMPANY": "1000"})], "sha")
    with pytest.raises(ValidationError):
        DataFeature.model_validate({**entry, "value": "1000"})


def test_raw_normalized_and_quarantine_rows_and_amounts_reconcile(imported):
    directory, report = imported
    assert (
        report["company_rows"] == report["normalized_company_rows"] + report["quarantined_company_rows"] == 9
    )
    assert report["quarantined_company_rows"] == 2
    assert report["quarantined_company_ids"] == ["u-mixed"]
    assert (
        sum(Decimal(item["amount"]) for item in report["payment_classification"].values())
        == Decimal(report["payment_amount"])
        == Decimal("1950.20")
    )
    assert (
        sum(item["payment_count"] for item in report["payment_classification"].values())
        == report["payment_count"]
        == 23
    )
    with session_factory()() as db:
        for name, expected in [(COMPANIES_FILE, 9), (PEOPLE_FILE, 7)]:
            stored = list(
                db.scalars(
                    select(ClientRawRow).where(ClientRawRow.file == name).order_by(ClientRawRow.row_number)
                )
            )
            with (directory / name).open(encoding="utf-8", newline="") as stream:
                source = list(csv.DictReader(stream, delimiter=";"))
            assert len(stored) == expected and [item.raw for item in stored] == source
        payments = list(db.scalars(select(Payment).order_by(Payment.row_number)))
        with (directory / PAYMENTS_FILE).open(encoding="utf-8", newline="") as stream:
            source = list(csv.DictReader(stream, delimiter=";"))
        assert [item.raw for item in payments] == source
        assert sum(item.amount for item in payments) == Decimal(report["payment_amount"])
        assert db.get(ImportBatch, report["version"]).report == report


def test_self_payments_unknown_parties_and_quarantine_are_separate(imported):
    with session_factory()() as db:
        context = company_context(db, "u-client")
        CompanyContextV2.model_validate(context)
        assert context["payment_summary"]["self_payments"] == {
            "amount": "900.00",
            "payment_count": 9,
            "row_count": 1,
        }
        assert context["payment_summary"]["outgoing"]["amount"] == "250.20"
        assert context["payment_summary"]["incoming"]["amount"] == "70.00"
        assert context["payment_summary"]["quarantined"]["amount"] == "330.00"
        assert context["payment_summary"]["period"] is None and context["payment_summary"]["unit"] is None
        outgoing = context["payment_links"]["outgoing"]
        assert [row["company_id"] for row in outgoing] == ["u-prospect", "outside"]
        assert outgoing[0]["amount"] == "200.20" and outgoing[0]["payment_count"] == 4
        assert outgoing[1]["counterparty_status"] == "placeholder"
        assert not ({"u-mixed", "u-client", "0"} & {row["company_id"] for row in outgoing})
        assert db.get(Company, "outside").is_placeholder


def test_identity_quarantine_does_not_swallow_ordinary_duplicates(imported):
    with session_factory()() as db:
        mixed = company_context(db, "u-mixed")
        assert mixed["identity_quality"] == "ambiguous"
        assert all(entry["value"] is None for entry in mixed["features"].values())
        assert mixed["group_id"] is None and mixed["relationships"] == []
        assert company_facts(mixed) == []
        duplicate = company_context(db, "u-dup")
        assert duplicate["identity_quality"] == "confirmed"
        assert duplicate["features"]["CL_PRODUCT_LOA_MARK"]["value"] == "1"
        assert duplicate["features"]["CL_PRODUCT_LOA_MARK"]["raw"] == ["1.0", "1"]
        assert company_context(db, "u-conflict")["features"]["REGION"]["quality"] == "conflicting"


def test_relations_and_person_residence_never_become_company_geography_or_ownership(imported):
    with session_factory()() as db:
        context = company_context(db, "u-client")
        assert context["features"]["CITY"]["value"] == "Город компании"
        assert "CITY_NAME" not in context["features"] and "RC_NAME" not in context["features"]
        kinds = {
            entry["relation_type"]
            for entry in context["relationships"]
            if entry["company_id"] == "u-prospect"
        }
        assert kinds == {"same_group", "shared_person", "payment"}
        assert not any("ownership" in entry or "supplier" in entry for entry in context["relationships"])
        assert "u-mixed" not in context["related_companies"]
        assert context["group_summary"]["observed_members"] == 3
        assert context["group_summary"]["revenue_covered_members"] == 0
        assert context["group_summary"]["revenue_sum"] is None
        assert context["group_summary"]["is_consolidated"] is False


def test_fts_and_negativemark_do_not_manufacture_import_export_or_negative_risk(imported):
    with session_factory()() as db:
        context = company_context(db, "u-client")
        facts = {fact.feature: fact for fact in company_facts(context)}
        assert "REVENUE_COMPANY" not in facts
        assert "импорт/экспорт не установлен" in facts["FTS_FLAG"].excerpt
        assert "ключевого собственника" in facts["NEGATIVEMARK"].excerpt
        assert "структура владения неизвестны" in facts["NEGATIVEMARK"].excerpt
        assert "NEGATIVE_MARK_1" not in context["features"]
        assert "trade_direction" in context["unknowns"]


def test_all_client_types_are_retained_but_only_clients_are_demo_candidates(imported):
    with session_factory()() as db:
        assert [db.get(Company, key).client_type for key in ["u-client", "u-prospect", "u-closed"]] == [
            "Client",
            "Prospect",
            "Closed Client",
        ]
        candidates = demo_candidates(db, 100)
        assert any(row.id == "u-client" for row in candidates)
        assert not ({"u-prospect", "u-closed", "u-mixed"} & {row.id for row in candidates})
        assert all(row.client_type == "Client" for row in candidates)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Membership)
                .where(Membership.company_id.in_(["u-client", "u-prospect", "u-closed"]))
            )
            == 0
        )


def test_context_v2_wire_and_ai_input_preserve_semantics_and_membership(client, imported):
    user = login(client)
    assert client.get("/companies/u-prospect/context").status_code == 403
    with session_factory()() as db, db.begin():
        db.add(Membership(user_id=user["id"], company_id="u-prospect", status="active"))
    response = client.get("/companies/u-prospect/context")
    assert response.status_code == 200
    parsed = CompanyContextV2.model_validate(response.json())
    assert parsed.client_type == "Prospect" and parsed.data_semantics_version == DATA_SEMANTICS_VERSION
    ai = BuildInsightInput.model_validate(
        {
            "company_context": response.json(),
            "user_focus": {"version": "test"},
            "event": {"id": "test", "title": "Test", "version": "v1", "publications": [], "evidence": []},
        }
    )
    assert type(ai.company_context) is CompanyContextV2
    assert client.get("/me").json()["system_role"] == "user"


def test_semantic_revision_reimports_same_files_and_changes_profile_version(imported, monkeypatch):
    directory, old = imported
    monkeypatch.setattr(client_import, "DATA_SEMANTICS_VERSION", "company-data-test-next")
    with session_factory()() as db, db.begin():
        new = import_clients(db, directory)
        assert new["files"] == old["files"] and new["version"] != old["version"]
        assert new["already_imported"] is False
        assert db.get(Company, "u-client").profile_version == new["version"]
    with session_factory()() as db, db.begin():
        assert import_clients(db, directory)["already_imported"] is True


def test_context_schema_export_has_no_drift():
    path = Path(__file__).resolve().parents[2] / "docs/contracts/company-context-v2.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == CompanyContextV2.model_json_schema()


@pytest.mark.parametrize(
    "example",
    json.loads(
        (Path(__file__).resolve().parents[2] / "docs/contracts/company-context-v2-examples.json").read_text(
            encoding="utf-8"
        )
    ),
    ids=lambda item: item["name"],
)
def test_shared_context_examples_validate_for_backend_and_ai(example):
    parsed = CompanyContextV2.model_validate(example["data"])
    assert parsed.schema_version == "v2"
    request = BuildInsightInput.model_validate(
        {
            "company_context": example["data"],
            "user_focus": {"version": "test"},
            "event": {"id": "test", "title": "Test", "version": "v1", "publications": [], "evidence": []},
        }
    )
    assert type(request.company_context) is CompanyContextV2

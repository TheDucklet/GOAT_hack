import csv
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.ai.benchmark import judge as judge_module
from app.ai.benchmark.data import (
    DEFAULT_DIRECTORY,
    event_payload,
    load_contexts,
    load_events,
    load_positions,
    pair_id,
)
from app.ai.benchmark.judge import essential_claims, judge_card
from app.ai.benchmark.labels import (
    adjudicate,
    cohen_kappa,
    company_line,
    read_labels,
    sheet_rows,
    write_sheet,
)
from app.ai.benchmark.metrics import (
    aggregate,
    grounded_rate,
    labeled_pairs,
    precision_recall_at_k,
    significant_pairs,
)
from app.ai.benchmark.rankers import baseline_scores, insight_scores, order
from app.ai.benchmark.report import card_stats, difference_rates, judge_summary, leak_findings
from app.ai.benchmark.targeted import corpus_change
from app.ai.providers import LLMError
from app.ai.schemas.inputs import EventPayload
from app.schemas import CompanyContextV2

NOW = datetime.fromisoformat("2026-10-23T18:00:00+03:00")


@pytest.fixture(scope="module")
def contexts():
    return load_contexts(DEFAULT_DIRECTORY)


@pytest.fixture(scope="module")
def events():
    return load_events(DEFAULT_DIRECTORY)


def claim(claim_id, text, refs=("evidence-1",), statement_type="fact"):
    return {
        "claim_id": claim_id,
        "text": text,
        "statement_type": statement_type,
        "evidence_refs": list(refs),
    }


def envelope(level="medium", mechanism=("шаг",), facts=(), bank_view=(), unknowns=("нет данных",)):
    return {
        "result": {
            "impact_level": level,
            "facts": [claim(f"f{i}", text) for i, text in enumerate(facts)],
            "bank_view": [claim(f"b{i}", text) for i, text in enumerate(bank_view)],
            "ai_interpretation": [],
            "mechanism": [
                claim(f"m{i}", text, statement_type="hypothesis") for i, text in enumerate(mechanism)
            ],
            "risks": [],
            "opportunities": [],
            "actions": [],
            "assumptions": [],
            "unknowns": list(unknowns),
            "personalized_summary": None,
            "impact_reason": None,
            "bank_view_context": {"status": "missing"},
        },
        "evidence": [
            {"id": "evidence-1", "kind": "news", "source_id": "pub-1", "excerpt": "дословный фрагмент"}
        ],
        "trace": {
            "validation": {"summary": {"removed": 1}},
            "impact": {"horizon_kind": "long_term"},
            "extra_searches": 0,
        },
    }


def record(
    pair, level="medium", mechanism=("шаг",), status="ok", context_id="B01-chief_accountant", **kwargs
):
    base = {"pair_id": pair, "context_id": context_id, "status": status}
    if status != "ok":
        return {**base, "error": "invalid_output"}
    return {**base, "latency_seconds": 2.0, "cost_rub": 0.3, "envelope": envelope(level, mechanism, **kwargs)}


def test_dataset_covers_protocol_minimums(contexts, events):
    assert len({item.company_id for item in contexts}) >= 6
    assert len({item.industry_group for item in contexts}) >= 3
    roles = {item.role for item in contexts if item.company_id == "B01"}
    assert len(roles) >= 2
    assert len(events) >= 10
    real = [item for item in events if item["source"] == "real_public_cbr"]
    assert real and all(item["url"] and item["published_at"] for item in real)
    assert {item["source"] for item in events} <= {"real_public_cbr", "synthetic"}
    assert any(item["used_in_tuning"] for item in events)
    assert any(not item["used_in_tuning"] for item in events)
    assert len({pair_id(c.context_id, e["id"]) for c in contexts for e in events}) == len(contexts) * len(
        events
    )


def test_contexts_and_events_match_contracts(contexts, events):
    for item in contexts:
        CompanyContextV2.model_validate(item.context)
    for item in events:
        EventPayload.model_validate(event_payload(item))
    assert load_positions(DEFAULT_DIRECTORY).keys() >= {item.role for item in contexts}


def test_company_line_reports_unknown_products_and_missing_revenue(contexts):
    sparse = next(item for item in contexts if item.company_id == "B06")
    line = company_line(sparse.context)
    assert "неизвестно" in line
    assert "ОКВЭД" in line


def test_sheet_has_every_pair_with_empty_labels(contexts, events, tmp_path):
    rows = sheet_rows(contexts, events, load_positions(DEFAULT_DIRECTORY))
    assert len(rows) == len(contexts) * len(events)
    assert all(row["label"] == "" for row in rows)
    path = tmp_path / "sheet.csv"
    write_sheet(path, rows)
    assert read_labels(path) == {}
    rows[0]["label"] = "2"
    write_sheet(path, rows)
    assert read_labels(path) == {rows[0]["pair_id"]: 2}


def test_read_labels_rejects_unknown_value(tmp_path):
    path = tmp_path / "labels-x.csv"
    path.write_text("pair_id,label\np1,5\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_labels(path)


def test_adjudication_separates_agreed_disputed_and_unlabeled():
    sets = {"a": {"p1": 2, "p2": 1, "p3": 0}, "b": {"p1": 2, "p2": 2}}
    result = adjudicate(sets, ["p1", "p2", "p3", "p4"])
    assert result["p1"]["status"] == "agreed" and result["p1"]["final"] == 2
    assert result["p2"]["status"] == "disputed" and result["p2"]["any_significant"]
    assert result["p3"]["status"] == "disputed"
    assert result["p4"]["status"] == "unlabeled"
    assert significant_pairs(result) == {"p1"}
    assert significant_pairs(result, include_disputed=True) == {"p1", "p2"}
    assert labeled_pairs(result) == {"p1"}
    assert labeled_pairs(result, include_disputed=True) == {"p1", "p2", "p3"}


def test_cohen_kappa_extremes():
    same = {"p1": 0, "p2": 1, "p3": 2, "p4": 2}
    assert cohen_kappa(same, dict(same)) == 1.0
    assert cohen_kappa(same, {"p1": 2, "p2": 0, "p3": 1, "p4": 0}) < 0
    assert cohen_kappa({}, same) is None
    assert cohen_kappa({"p1": 2, "p2": 2}, {"p1": 2, "p2": 2}) is None


def test_precision_recall_use_only_labeled_pool():
    ranking = ["a", "b", "c", "d", "e", "f"]
    result = precision_recall_at_k(ranking, {"a", "c", "f"}, {"a", "b", "c", "d", "e", "f"})
    assert result["hits"] == 2
    assert result["precision"] == 0.4
    assert result["recall"] == pytest.approx(0.6667, abs=1e-4)
    skipped = precision_recall_at_k(ranking, {"a", "c"}, {"a", "c", "d", "e", "f"})
    assert skipped["returned"] == 5 and skipped["hits"] == 2


def test_precision_is_na_for_small_pool_and_recall_na_without_significant():
    small = precision_recall_at_k(["a", "b", "c"], {"a"}, {"a", "b", "c"})
    assert small["precision"] is None and small["recall"] == 1.0
    none = precision_recall_at_k(["a", "b", "c", "d", "e"], set(), {"a", "b", "c", "d", "e"})
    assert none["precision"] == 0.0 and none["recall"] is None


def test_aggregate_reports_micro_macro_and_na_counts():
    rows = [
        {"k": 5, "hits": 4, "significant_in_pool": 4, "precision": 0.8, "recall": 1.0},
        {"k": 5, "hits": 1, "significant_in_pool": 3, "precision": 0.2, "recall": 0.3333},
        {"k": 5, "hits": 0, "significant_in_pool": 0, "precision": 0.0, "recall": None},
        {"k": 5, "hits": 1, "significant_in_pool": 1, "precision": None, "recall": 1.0},
    ]
    summary = aggregate(rows)
    assert summary["precision_micro"] == pytest.approx(5 / 15, abs=1e-4)
    assert summary["precision_macro"] == pytest.approx(0.3333, abs=1e-4)
    assert (summary["precision_numerator"], summary["precision_denominator"]) == (5, 15)
    assert (summary["recall_numerator"], summary["recall_denominator"]) == (6, 8)
    assert (summary["precision_ceiling_numerator"], summary["precision_ceiling_micro"]) == (
        7,
        round(7 / 15, 4),
    )
    assert summary["precision_na_contexts"] == 1 and summary["recall_na_contexts"] == 1
    assert aggregate([])["precision_micro"] is None


def test_grounded_rate_has_na_for_empty():
    assert grounded_rate([]) == {"claims": 0, "grounded": 0, "rate": None}
    assert grounded_rate([{"grounded": True}, {"grounded": False}])["rate"] == 0.5


def test_ranker_order_is_deterministic_and_prefers_newer_on_ties():
    events = [
        {"id": "old", "published_at": "2026-10-01T10:00:00+03:00"},
        {"id": "new", "published_at": "2026-10-20T10:00:00+03:00"},
        {"id": "top", "published_at": "2026-10-10T10:00:00+03:00"},
    ]
    assert order({"old": 1.0, "new": 1.0, "top": 2.0}, events) == ["top", "new", "old"]


def test_insight_scores_rank_level_first_then_mechanism():
    cards = {
        "low_long": envelope("low", mechanism=("a", "b", "c")),
        "high_short": envelope("high", mechanism=("a",)),
        "high_long": envelope("high", mechanism=("a", "b")),
        "undetermined": envelope("undetermined", mechanism=()),
    }
    scores = insight_scores(cards, {"low_long": 99.0})
    ranked = sorted(scores, key=lambda key: -scores[key])
    assert ranked == ["high_long", "high_short", "low_long", "undetermined"]


def test_baseline_scores_use_current_event_ranker(contexts, events):
    context = next(item for item in contexts if item.context_id == "B01-chief_accountant")
    scores = baseline_scores(context.context, {"topics": [], "priorities": []}, events, NOW)
    assert set(scores) == {item["id"] for item in events}
    assert all(isinstance(value, int | float) for value in scores.values())


def test_card_stats_counts_errors_and_levels():
    pairs = {
        "p1": record("p1", "high"),
        "p2": record("p2", "low"),
        "p3": record("p3", status="error"),
    }
    stats = card_stats(pairs)
    assert (stats["pairs"], stats["ok"], stats["errors"]) == (3, 2, 1)
    assert stats["impact_levels"] == {"high": 1, "low": 1}
    assert stats["validator_removed_claims"] == 2
    assert stats["cost_rub"]["total"] == 0.6


def test_leak_findings_detect_foreign_evidence_and_company_identifiers(contexts):
    lookup = {item.context_id: item for item in contexts}
    clean = record("p1", facts=("Выручка отрасли выросла.",))
    leaking = record("p2", facts=("Компания B03 покупает металл.",))
    leaking["envelope"]["evidence"].append(
        {"id": "e9", "kind": "company", "source_id": "B05", "excerpt": "x"}
    )
    findings = leak_findings({"p1": clean, "p2": leaking}, lookup)
    assert {(item["pair_id"], item["kind"]) for item in findings} == {
        ("p2", "foreign_company_evidence"),
        ("p2", "company_identifier_in_text"),
    }


def test_difference_rates_compare_mechanisms_by_stems():
    pairs = {
        pair_id("L", "e1"): record(
            pair_id("L", "e1"), mechanism=("ставка кредита растет, проценты дорожают",)
        ),
        pair_id("R", "e1"): record(pair_id("R", "e1"), mechanism=("поставщик меняет цены на сталь",)),
        pair_id("L", "e2"): record(pair_id("L", "e2"), mechanism=("налог платится ежемесячно",)),
        pair_id("R", "e2"): record(pair_id("R", "e2"), mechanism=("налог платится ежемесячно",)),
        pair_id("L", "e3"): record(pair_id("L", "e3"), mechanism=()),
        pair_id("R", "e3"): record(pair_id("R", "e3"), mechanism=("шаг",)),
    }
    result = difference_rates(pairs, [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}], "L", "R")
    assert (result["events_compared"], result["different"], result["rate"]) == (2, 1, 0.5)
    assert difference_rates({}, [{"id": "e1"}], "L", "R")["rate"] is None


def test_judge_summary_collects_critical_findings(tmp_path):
    judge_dir = tmp_path / "judge"
    judge_dir.mkdir()
    claims = [
        {"claim_id": "1", "section": "facts", "verdict": "supported", "grounded": True, "text": "а"},
        {"claim_id": "2", "section": "facts", "verdict": "unsupported", "grounded": False, "text": "б"},
        {"claim_id": "3", "section": "bank_view", "verdict": "contradicted", "grounded": False, "text": "в"},
        {"claim_id": "4", "section": "mechanism", "verdict": "not_judged", "grounded": False, "text": "г"},
    ]
    (judge_dir / "p1.json").write_text(json.dumps({"claims": claims}, ensure_ascii=False), encoding="utf-8")
    summary = judge_summary(tmp_path)
    assert summary["overall"] == {"claims": 4, "grounded": 1, "rate": 0.25}
    assert len(summary["critical_unsupported_facts"]) == 2
    assert len(summary["false_bank_positions"]) == 1
    assert summary["not_judged"] == 1
    assert judge_summary(tmp_path / "missing")["overall"]["rate"] is None


def test_essential_claims_attach_source_excerpts():
    claims = essential_claims(envelope(facts=("факт",), bank_view=("позиция",)))
    assert {item["section"] for item in claims} == {"facts", "bank_view", "mechanism"}
    assert all(item["sources"] == ["дословный фрагмент"] for item in claims)


def stub_llm(monkeypatch, verdicts=None, error=None):
    def call(task, payload, tokens, response_model=None, temperature=0.0):
        if error:
            raise error
        batch = json.loads(payload.user)["claims"]
        data = {
            "verdicts": [
                {"id": item["id"], "verdict": (verdicts or {}).get(item["id"], "supported"), "reason": "ok"}
                for item in batch
            ]
        }
        usage = SimpleNamespace(cost_rub=0.01, input_tokens=10, output_tokens=5)
        return SimpleNamespace(data=data, model_id="judge-model", usage=usage)

    monkeypatch.setattr(judge_module, "call_llm", call)


def test_judge_card_maps_verdicts_and_marks_missing_as_not_judged(monkeypatch):
    stub_llm(monkeypatch, {"f0": "unsupported", "b0": "bogus"})
    judged = judge_card(envelope(facts=("факт",), bank_view=("позиция",)))
    verdicts = {item["claim_id"]: item for item in judged["claims"]}
    assert verdicts["f0"]["verdict"] == "unsupported" and not verdicts["f0"]["grounded"]
    assert verdicts["b0"]["verdict"] == "not_judged"
    assert verdicts["m0"]["grounded"]
    assert judged["usage"][0]["model"] == "judge-model"


def test_judge_card_tolerates_recoverable_errors_but_not_budget(monkeypatch):
    stub_llm(monkeypatch, error=LLMError("invalid_json", "x"))
    judged = judge_card(envelope(facts=("факт",)))
    assert all(item["verdict"] == "not_judged" for item in judged["claims"])
    stub_llm(monkeypatch, error=LLMError("budget_exhausted", "x"))
    with pytest.raises(LLMError):
        judge_card(envelope(facts=("факт",)))


def test_corpus_change_recomputes_only_for_new_corpus_version():
    result = corpus_change()
    assert result["passed"] and result["computations"] == 2


def test_essential_claims_give_judge_full_publication_for_news_evidence():
    card = envelope(facts=("факт из второго предложения",))
    plain = essential_claims(card)
    full = essential_claims(card, {"pub-1": "Первое предложение. Второе предложение с фактом."})
    assert plain[0]["sources"] == ["дословный фрагмент"]
    assert full[0]["sources"] == ["Первое предложение. Второе предложение с фактом."]
    bank = envelope(bank_view=("позиция",))
    bank["evidence"].append(
        {"id": "evidence-2", "kind": "bank", "source_id": "doc", "excerpt": "фрагмент банка"}
    )
    bank["result"]["bank_view"][0]["evidence_refs"] = ["evidence-2"]
    sources = {
        item["section"]: item["sources"] for item in essential_claims(bank, {"doc": "не должно подставиться"})
    }
    assert sources["bank_view"] == ["фрагмент банка"]


def test_calibration_sheets_are_blind_disjoint_and_reproducible(tmp_path):
    from pathlib import Path

    from app.ai.benchmark.calibration import SEED, build_sheets

    root = Path(__file__).resolve().parents[2]
    run = root / "docs" / "quality" / "benchmark" / "runs" / "run-1"
    selection = build_sheets(run, tmp_path, SEED)
    assert selection["critical_occurrences"] == 18 and selection["critical_unique"] == 6
    assert selection["calibration_rows"] >= 6 + 30 and selection["control_rows"] >= 30
    calibration = list(
        csv.DictReader((tmp_path / "calibration-sheet.csv").open(encoding="utf-8-sig", newline=""))
    )
    control = list(csv.DictReader((tmp_path / "control-sheet.csv").open(encoding="utf-8-sig", newline="")))
    assert {"verdict", "premises_supported"} <= set(calibration[0])
    assert "judge" not in " ".join(calibration[0]) and all(
        not row["verdict"] for row in calibration + control
    )
    assert {row["claim"] for row in calibration}.isdisjoint({row["claim"] for row in control})
    assert {row["section"] for row in calibration} >= {"facts", "bank_view", "mechanism", "scenario"}
    saved = json.loads(
        (root / "docs" / "quality" / "benchmark" / "calibration" / "selection.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved == selection


def test_new_event_set_is_fixed_deterministic_and_disjoint_from_the_first_run():
    import hashlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "docs" / "quality" / "benchmark"
    new = json.loads((root / "events-v2" / "events.json").read_text(encoding="utf-8"))
    old = json.loads((root / "events.json").read_text(encoding="utf-8"))["events"]
    events = new["events"]
    assert len(events) == 6 and sum(item["source"] == "real_public_cbr" for item in events) >= 3
    assert all(item["published_at"] <= new["as_of"] for item in events)
    assert all(hashlib.sha256(item["text"].encode("utf-8")).hexdigest() == item["sha256"] for item in events)
    assert all(
        item["url"] and item["text_kind"] == "full_text" for item in events if item["source"] != "synthetic"
    )
    assert all(not item["used_in_tuning"] for item in events)
    assert not {item["url"] for item in events if item["url"]} & {
        item["url"] for item in old if item.get("url")
    }
    assert {"macro", "regulatory"} <= {item["category"] for item in events}
    assert not any("Фото на превью" in item["text"] or "\xa0" in item["text"] for item in events)
    sheet = list(
        csv.DictReader(
            (root / "events-v2" / "labeling" / "sheet-v2.csv").open(encoding="utf-8-sig", newline="")
        )
    )
    assert len(sheet) == 42 and all(not row["label"] for row in sheet)


def test_pair_run_retries_only_transient_errors_and_never_regenerates_a_blocked_card(monkeypatch):
    from app.ai.benchmark import runner
    from app.ai.benchmark.data import BenchmarkContext
    from app.ai.providers import LLMError

    calls = {"count": 0}
    envelope = {
        "trace": {
            "steps": [{"llm": "x", "cost_rub": 0.1}],
            "publication": {"decision": "block", "usage": [], "cost_rub": 0.02},
        },
        "result": {},
    }

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise LLMError("provider_unavailable", "r")
        return envelope

    monkeypatch.setattr(runner, "build_published_insight", flaky)
    context = BenchmarkContext("B-r", "B", "r", "g", {})
    record = runner.run_pair(context, {"id": "e"}, {}, lambda *a: {"items": []}, retries=1)
    assert (
        record["status"] == "blocked"
        and calls["count"] == 2
        and record["failed_attempts"][0]["error"] == "provider_unavailable"
    )
    assert record["cost_rub"] == pytest.approx(0.12)
    calls["count"] = 0
    monkeypatch.setattr(
        runner, "build_published_insight", lambda *a, **k: (_ for _ in ()).throw(LLMError("timeout", "r"))
    )
    lost = runner.run_pair(context, {"id": "e"}, {}, lambda *a: {"items": []}, retries=1)
    assert lost["status"] == "error" and len(lost["failed_attempts"]) == 2
    monkeypatch.setattr(
        runner,
        "build_published_insight",
        lambda *a, **k: (_ for _ in ()).throw(LLMError("budget_exhausted", "r")),
    )
    with pytest.raises(LLMError):
        runner.run_pair(context, {"id": "e"}, {}, lambda *a: {"items": []}, retries=1)


def test_every_verifier_prompt_requires_a_decomposition_into_parts():
    from app.ai.gate.prompts import GATE_SYSTEM_PROMPT
    from app.ai.summarization.prompts import FACT_CHECK_SYSTEM_PROMPT

    for prompt in (GATE_SYSTEM_PROMPT, FACT_CHECK_SYSTEM_PROMPT):
        assert '"parts"' in prompt and "not_in_sources" in prompt and "in_sources" in prompt


def test_event_with_no_verified_facts_is_not_backfilled_with_the_first_sentence():
    from app.ai.insights.build import event_facts
    from app.ai.schemas import EventPayload

    base = {
        "id": "e",
        "title": "t",
        "published_at": "2026-10-01T10:00:00+03:00",
        "version": "v",
        "publications": [{"id": "p", "url": "https://x.example/1", "text": "Первое предложение. Второе."}],
        "evidence": [
            {
                "id": "ev",
                "kind": "news",
                "source_id": "p",
                "version": "v",
                "locator": {},
                "excerpt": "Первое предложение.",
            }
        ],
    }
    assert event_facts(EventPayload.model_validate({**base, "facts": []})) == []
    assert len(event_facts(EventPayload.model_validate({**base, "facts": None}))) == 1


def test_demo_trace_v2_shows_rejected_claim_extra_search_and_dated_page(tmp_path):
    from pathlib import Path

    from app.ai.benchmark.demo import DEFAULT_PAIR, build_demo

    root = Path(__file__).resolve().parents[2]
    run = root / "docs" / "quality" / "benchmark" / "runs" / "run-1"
    demo = build_demo(
        run,
        DEFAULT_PAIR,
        root / "docs" / "ai" / "fixtures" / "bank-chunks.json",
        root / "docs" / "quality" / "benchmark",
    )
    kinds = [step["step"] for step in demo["steps"]]
    assert "retry" in kinds and kinds[-1] == "stop"
    assert demo["rejected_bank_claims"]
    for claim in demo["bank_view"]:
        for source in claim["sources"]:
            assert source["page"] >= 1 and source["document_date"] and source["quote"]
    assert all(
        item["document_date"]
        for step in demo["steps"]
        if step["step"] == "search"
        for item in step["fragments"]
    )
    assert demo["selection"]["cards_total"] == 84
    saved = json.loads((root / "docs" / "demo" / "agent-trace-v2.json").read_text(encoding="utf-8"))
    assert saved == demo


def test_frozen_judge_prompts_keep_their_recorded_hashes():
    from app.ai.benchmark.judge_prompts import CURRENT_JUDGE_VERSION, JUDGE_PROMPTS, prompt_sha256

    assert prompt_sha256("judge-2") == "72a1cefe3d5893e6d93333da510cc9e8e186fe3f8a4f8c2b550641d157cc8aba"
    assert prompt_sha256("judge-3") == "8c0a5d2d821b40bc25ece6d57f9f4d41300f84088ab993b9f658ba8a9f77fc60"
    assert CURRENT_JUDGE_VERSION in JUDGE_PROMPTS and JUDGE_PROMPTS["judge-2"] != JUDGE_PROMPTS["judge-3"]


def test_judge_prompt_does_not_follow_the_publication_gate_prompt(monkeypatch):
    from app.ai.benchmark import judge
    from app.ai.gate import prompts as gate_prompts

    before = judge.JUDGE2_SYSTEM_PROMPT
    monkeypatch.setattr(
        gate_prompts, "GATE_SYSTEM_PROMPT", gate_prompts.GATE_SYSTEM_PROMPT + " Новое правило."
    )
    assert judge.JUDGE2_SYSTEM_PROMPT == before and "Новое правило" not in judge.JUDGE2_SYSTEM_PROMPT


def test_judge_result_records_identity_and_is_reused_only_for_the_same_card(monkeypatch):
    from app.ai.benchmark import judge

    card = {"result": {"facts": []}, "evidence": []}
    same = judge.judge_identity(card)
    assert same["prompt_sha256"] == judge.prompt_sha256(same["judge_version"]) and same["model"]
    assert judge.judge_identity({"result": {"facts": [{"x": 1}]}, "evidence": []}) != same
    assert judge.judge_identity(card, "judge-2") != same
    monkeypatch.setattr(judge, "verify_claims", lambda *args, **kwargs: ({}, []))
    monkeypatch.setattr(judge, "essential_claims", lambda *args, **kwargs: [])
    saved = judge.judge_card_v2(card, {}, {})
    assert saved["identity"] == same and saved["judge_version"] == same["judge_version"]


def test_metrics_flag_a_directory_that_mixes_different_judges(tmp_path):
    from app.ai.benchmark.report_v2 import judge_v2

    directory = tmp_path / "judge2"
    directory.mkdir()
    for name, sha in (("a", "1"), ("b", "2")):
        (directory / f"{name}.json").write_text(
            json.dumps({"judge_version": "judge-3", "identity": {"prompt_sha256": sha}, "claims": []}),
            encoding="utf-8",
        )
    report = judge_v2(tmp_path, {})
    assert (
        report["mixed_judges"] is True and report["judge_version"] == "mixed" and len(report["judges"]) == 2
    )

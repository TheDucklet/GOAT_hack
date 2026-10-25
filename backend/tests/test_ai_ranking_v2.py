import json
import math
from pathlib import Path

import pytest

from app.ai.benchmark.ranking_v2 import aggregate_v2, compare, context_result, dcg, gates, order_v2

TARGETS = json.loads(
    (Path(__file__).resolve().parents[2] / "docs/quality/benchmark/targets-ranking-v2.json").read_text(
        encoding="utf-8"
    )
)["ranking"]


def labels(**kwargs):
    return dict(kwargs)


def test_gains_are_zero_one_three_and_dcg_uses_log_positions():
    assert dcg([2, 1, 0]) == pytest.approx(3 / math.log2(2) + 1 / math.log2(3))


def test_ideal_order_gives_one_and_missing_slots_have_zero_gain():
    pool = labels(a=2, b=1, c=0, d=0, e=0, f=0)
    best = context_result(["a", "b", "c", "d", "e"], pool)
    assert best["ndcg"] == 1.0 and best["hits"] == 1 and best["recall"] == 1.0
    worst = context_result(["c", "d", "e", "f"], pool)
    assert worst["ndcg"] == 0.0 and worst["returned"] == 4 and worst["recall"] == 0.0
    empty = context_result([], pool)
    assert empty["ndcg"] == 0.0 and empty["dcg"] == 0.0


def test_refusal_does_not_shrink_the_denominator():
    pool = labels(a=2, b=2, c=1)
    full = context_result(["a", "b", "c"], pool)
    refused = context_result(["b", "c"], pool)
    assert refused["idcg"] == full["idcg"] and refused["ndcg"] < full["ndcg"]


def test_undefined_cases_stay_na_and_are_counted():
    rows = [
        context_result(["a"], labels(a=0, b=0)),
        context_result(["a"], labels(a=2, b=1)),
    ]
    assert rows[0]["ndcg"] is None and rows[0]["recall"] is None
    summary = aggregate_v2(rows)
    assert summary["ndcg_na"] == 1 and summary["recall_na"] == 1 and summary["ndcg_defined"] == 1


def test_pooled_ndcg_is_sum_of_dcg_over_sum_of_idcg_not_the_mean():
    rows = [
        context_result(["a", "b"], labels(a=2, b=0)),
        context_result(["c", "d"], labels(c=0, d=2, e=2)),
    ]
    summary = aggregate_v2(rows)
    expected = sum(item["dcg"] for item in rows) / sum(item["idcg"] for item in rows)
    assert summary["ndcg_pooled"] == pytest.approx(expected, abs=1e-4)
    assert summary["ndcg_pooled"] != summary["ndcg_macro"]
    assert summary["recall_micro"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["precision_ceiling_micro"] == pytest.approx((0.2 + 0.4) / 2)


def test_ties_are_ordered_by_score_then_event_id():
    assert order_v2({"b": 1.0, "a": 1.0, "c": 2.0}) == ["c", "a", "b"]


def test_comparison_and_gates_follow_the_decision_record():
    good = {key: context_result([key + "1"], labels(**{key + "1": 2})) for key in "abcdefg"}
    weak = {key: context_result(["x"], labels(**{key + "1": 2, "x": 0})) for key in "abcdefg"}
    comparison = compare(good, weak)
    assert comparison["share_not_worse"] == 1.0 and all(
        value >= 0 for value in comparison["differences"].values()
    )
    result = gates(aggregate_v2(list(good.values())), comparison, TARGETS)
    assert result["passed"] and result["sufficient"]["passed"]
    failed = gates(aggregate_v2(list(weak.values())), compare(weak, good), TARGETS)
    assert not failed["passed"] and not failed["ndcg_macro"]["passed"]


def test_gate_is_incomplete_when_too_few_contexts_are_defined():
    rows = {key: context_result(["a"], labels(a=0, b=0)) for key in "abcdefg"}
    rows["a"] = context_result(["a1"], labels(a1=2))
    comparison = compare(rows, rows)
    assert not gates(aggregate_v2(list(rows.values())), comparison, TARGETS)["sufficient"]["passed"]

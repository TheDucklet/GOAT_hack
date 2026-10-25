import collections
from datetime import datetime
from pathlib import Path
from statistics import median

from app.ai.benchmark.data import BenchmarkContext, pair_id
from app.ai.benchmark.judge import JUDGE2_PROMPT_VERSION
from app.ai.benchmark.labels import adjudicate, agreement_report
from app.ai.benchmark.metrics import IMPACT_ORDER, grounded_rate
from app.ai.benchmark.rankers import baseline_scores
from app.ai.benchmark.ranking_v2 import aggregate_v2, compare, context_result, gates, order_v2
from app.ai.benchmark.report import CRITICAL_SECTIONS, difference_rates, leak_findings, load_pairs
from app.ai.benchmark.runner import read

BASELINE, INSIGHT = "baseline", "insight"
ESSENTIAL_SECTIONS = ("facts", "bank_view", "ai_interpretation", "mechanism")
ESSENTIAL_SINGLE = ("personalized_summary", "impact_reason")


def insight_value(envelope: dict, baseline: float) -> float:
    result = envelope["result"]
    return IMPACT_ORDER[result["impact_level"]] * 1000 + len(result["mechanism"]) * 10 + baseline


def coverage(pairs: dict, expected: list[str]) -> dict:
    states = collections.Counter(pairs[key]["status"] if key in pairs else "missing" for key in expected)
    first_failures = sum(len(item.get("failed_attempts", [])) for item in pairs.values())
    costs = [item.get("cost_rub", 0.0) for item in pairs.values()]
    latency = sorted(item["latency_seconds"] for item in pairs.values() if "latency_seconds" in item)
    return {
        "requested": len(expected),
        "ready": states["ok"],
        "ready_coverage": round(states["ok"] / len(expected), 4) if expected else None,
        "final_quality_refusals": states["blocked"],
        "lost_pairs": states["error"] + states["missing"] + states["not_started_budget"],
        "failed_attempts_before_success_or_loss": first_failures,
        "states": dict(states),
        "cost_rub": round(sum(costs), 4),
        "latency_median": round(median(latency), 2) if latency else None,
        "latency_p90": latency[int(0.9 * (len(latency) - 1))] if latency else None,
    }


def block_reasons(pairs: dict) -> dict:
    reasons = collections.Counter()
    removed = collections.Counter()
    repairs = collections.Counter()
    for item in pairs.values():
        report = (item.get("envelope") or {}).get("trace", {}).get("publication")
        if not report:
            continue
        repairs[report.get("repair_attempts", 0)] += 1
        for entry in report.get("removed", []):
            removed[entry["section"]] += 1
        if report["decision"] != "allow":
            reasons[report.get("stop_reason", "unknown")] += 1
    return {
        "block_reasons": dict(reasons),
        "removed_by_section": dict(removed),
        "repair_attempts": {str(key): value for key, value in sorted(repairs.items())},
    }


def positive_cases(pairs: dict, required: list[str], regression: str | None) -> dict:
    rows = []
    for key in [*required, *([regression] if regression else [])]:
        item = pairs.get(key)
        if not item or item["status"] != "ok":
            rows.append({"pair_id": key, "passed": False, "reason": "карточка не опубликована"})
            continue
        result = item["envelope"]["result"]
        evidence = {entry["id"]: entry for entry in item["envelope"]["evidence"]}
        kinds = {
            evidence[ref]["kind"]
            for claim in result["mechanism"]
            for ref in claim["evidence_refs"]
            if ref in evidence
        }
        meaningful = bool(result["mechanism"]) and {"news", "company"} <= kinds
        expected_level = result["impact_level"] == "undetermined" if key.startswith("B06") else True
        rows.append(
            {
                "pair_id": key,
                "passed": meaningful and expected_level,
                "impact_level": result["impact_level"],
                "mechanism_steps": len(result["mechanism"]),
                "evidence_kinds": sorted(kinds),
                "regression": key == regression,
            }
        )
    core = [row for row in rows if not row.get("regression")]
    return {
        "required": len(core),
        "passed": sum(1 for row in core if row["passed"]),
        "regression_passed": next((row["passed"] for row in rows if row.get("regression")), None),
        "rows": rows,
    }


def judge_v2(run_dir: Path, pairs: dict) -> dict:
    directory = run_dir / "judge2"
    claims = []
    judges = set()
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        saved = read(path)
        identity = saved.get("identity") or {}
        judges.add((saved.get("judge_version", "legacy"), identity.get("prompt_sha256", "unrecorded")))
        for claim in saved["claims"]:
            claims.append({**claim, "pair_id": path.stem})
    expected = 0
    for item in pairs.values():
        if item["status"] != "ok":
            continue
        result = item["envelope"]["result"]
        expected += sum(len(result.get(section) or []) for section in ESSENTIAL_SECTIONS)
        expected += sum(1 for section in ESSENTIAL_SINGLE if result.get(section))
    by_section = {
        section: grounded_rate([item for item in claims if item["section"] == section])
        for section in sorted({item["section"] for item in claims})
    }
    critical = [
        item
        for item in claims
        if item["section"] in CRITICAL_SECTIONS and item["verdict"] in {"unsupported", "contradicted"}
    ]
    return {
        "judge_version": next(iter(judges))[0]
        if len(judges) == 1
        else ("mixed" if judges else JUDGE2_PROMPT_VERSION),
        "judges": [{"version": version, "prompt_sha256": sha} for version, sha in sorted(judges)],
        "mixed_judges": len(judges) > 1,
        "overall": grounded_rate(claims),
        "by_section": by_section,
        "expected_claims": expected,
        "judged_claims": len(claims),
        "verification_coverage": round(len(claims) / expected, 4) if expected else None,
        "not_judged": sum(1 for item in claims if item["verdict"] == "not_judged"),
        "critical_occurrences": len(critical),
        "critical_unique": len({(item["section"], item["text"]) for item in critical}),
        "false_bank_positions": sum(1 for item in critical if item["section"] == "bank_view"),
        "critical_examples": critical[:20],
    }


def ranking_block(
    contexts: list[BenchmarkContext],
    events: list[dict],
    pairs: dict,
    focus: dict,
    labels: dict[str, int],
    now: datetime,
    targets: dict,
    complete: bool = True,
) -> dict:
    rows: dict[str, dict] = {BASELINE: {}, INSIGHT: {}}
    for context in contexts:
        keys = {event["id"]: pair_id(context.context_id, event["id"]) for event in events}
        pool = {key: labels[key] for key in keys.values() if key in labels}
        base = baseline_scores(context.context, focus[context.role], events, now)
        baseline_order = [keys[key] for key in order_v2(base)]
        cards = {
            event_id: pairs[key]["envelope"]
            for event_id, key in keys.items()
            if key in pairs and pairs[key]["status"] == "ok"
        }
        scores = {event_id: insight_value(card, base.get(event_id, 0.0)) for event_id, card in cards.items()}
        insight_order = [keys[key] for key in order_v2(scores)]
        rows[BASELINE][context.context_id] = context_result(baseline_order, pool)
        rows[INSIGHT][context.context_id] = context_result(insight_order, pool)
    comparison = compare(rows[INSIGHT], rows[BASELINE])
    summary = {name: aggregate_v2(list(value.values())) for name, value in rows.items()}
    return {
        "per_context": rows,
        "summary": summary,
        "comparison": comparison,
        "gates": gates(summary[INSIGHT], comparison, targets["ranking"], complete),
    }


def final_labels(adjudicated: dict) -> dict[str, int]:
    return {key: item["final"] for key, item in adjudicated.items() if item["status"] == "agreed"}


def build_metrics_v2(
    run_dir: Path,
    label_sets: dict[str, dict[str, int]],
    contexts: list[BenchmarkContext],
    events: list[dict],
    targets: dict,
    set_name: str,
    now: datetime,
) -> dict:
    pairs = load_pairs(run_dir)
    expected = [pair_id(context.context_id, event["id"]) for context in contexts for event in events]
    adjudicated = adjudicate(label_sets, expected) if label_sets else {}
    focus = read(run_dir / "focuses.json")
    lookup = {context.context_id: context for context in contexts}
    ok_pairs = {key: item for key, item in pairs.items() if item["status"] == "ok"}
    labels = final_labels(adjudicated)
    unresolved = sum(1 for item in adjudicated.values() if item["status"] != "agreed")
    required = [key for key in targets["positive_cases"] if key in expected]
    case = targets["coverage"]["regression_case"]
    return {
        "set": set_name,
        "run": read(run_dir / "run.json"),
        "coverage": coverage(pairs, expected),
        "gate_report": block_reasons(pairs),
        "positive_cases": positive_cases(pairs, required, case if case in expected else None),
        "labels": {
            "status": "COMPLETE" if label_sets and not unresolved else "INCOMPLETE",
            "agreed": len(labels),
            "unresolved": unresolved,
            "labelers": agreement_report(label_sets) if label_sets else None,
        },
        "ranking": (
            ranking_block(contexts, events, pairs, focus, labels, now, targets, not unresolved)
            if labels
            else "N/A: метки значимости не получены"
        ),
        "grounded_claims": judge_v2(run_dir, pairs),
        "leaks": leak_findings(ok_pairs, lookup),
        "role_difference": (
            difference_rates(ok_pairs, events, "B01-chief_accountant", "B01-procurement_director")
            if {"B01-chief_accountant", "B01-procurement_director"} <= set(lookup)
            else None
        ),
    }

import re
from pathlib import Path
from statistics import mean, median

from app.ai.benchmark.data import BenchmarkContext, pair_id
from app.ai.benchmark.labels import adjudicate, agreement_report, read_labels
from app.ai.benchmark.metrics import (
    aggregate,
    grounded_rate,
    labeled_pairs,
    precision_recall_at_k,
    significant_pairs,
)
from app.ai.benchmark.rankers import baseline_scores, insight_scores, order
from app.ai.benchmark.runner import AS_OF_NOW, read
from app.ai.summarization.conflicts import context_stems

COMPANY_ID = re.compile(r"\bB0\d\b|\bU_\d+\b")
CRITICAL_SECTIONS = ("facts", "bank_view")


def load_pairs(run_dir: Path) -> dict[str, dict]:
    return {
        item["pair_id"]: item for item in (read(path) for path in sorted((run_dir / "pairs").glob("*.json")))
    }


def load_label_sets(directory: Path) -> dict[str, dict[str, int]]:
    return {
        path.stem.removeprefix("labels-"): read_labels(path)
        for path in sorted(directory.glob("labels-*.csv"))
    }


def ranking_metrics(
    run_dir: Path,
    contexts: list[BenchmarkContext],
    events: list[dict],
    pairs: dict,
    adjudicated: dict,
    include_disputed: bool,
) -> dict:
    significant = significant_pairs(adjudicated, include_disputed)
    labeled = labeled_pairs(adjudicated, include_disputed)
    focus = read(run_dir / "focuses.json")
    per_context = {"baseline": [], "insight": []}
    for context in contexts:
        ids = [pair_id(context.context_id, event["id"]) for event in events]
        if not all(item in pairs and pairs[item]["status"] == "ok" for item in ids):
            continue
        pool = {item for item in ids if item in labeled}
        base = baseline_scores(context.context, focus[context.role], events, AS_OF_NOW)
        cards = {event["id"]: pairs[pair_id(context.context_id, event["id"])]["envelope"] for event in events}
        insight = insight_scores(cards, base)
        for name, scores in (("baseline", base), ("insight", insight)):
            ranking = [pair_id(context.context_id, key) for key in order(scores, events)]
            result = precision_recall_at_k(ranking, significant, pool)
            per_context[name].append({"context_id": context.context_id, **result})
    return {name: {"per_context": rows, "summary": aggregate(rows)} for name, rows in per_context.items()}


def card_stats(pairs: dict) -> dict:
    ok = [item for item in pairs.values() if item["status"] == "ok"]
    levels: dict[str, int] = {}
    for item in ok:
        level = item["envelope"]["result"]["impact_level"]
        levels[level] = levels.get(level, 0) + 1
    latency = sorted(item["latency_seconds"] for item in ok)
    costs = [item["cost_rub"] for item in ok]
    return {
        "pairs": len(pairs),
        "ok": len(ok),
        "errors": len(pairs) - len(ok),
        "impact_levels": dict(sorted(levels.items())),
        "latency_seconds": {
            "median": round(median(latency), 2) if latency else None,
            "p90": latency[int(0.9 * (len(latency) - 1))] if latency else None,
            "max": latency[-1] if latency else None,
        },
        "cost_rub": {"total": round(sum(costs), 4), "mean": round(mean(costs), 4) if costs else None},
        "bank_view_present": sum(1 for item in ok if item["envelope"]["result"]["bank_view"]),
        "validator_removed_claims": sum(
            item["envelope"]["trace"]["validation"]["summary"]["removed"] for item in ok
        ),
    }


def leak_findings(pairs: dict, contexts: dict[str, BenchmarkContext]) -> list[dict]:
    findings = []
    for item in pairs.values():
        if item["status"] != "ok":
            continue
        company = contexts[item["context_id"]].company_id
        envelope = item["envelope"]
        for evidence in envelope["evidence"]:
            if evidence["kind"] == "company" and evidence["source_id"] != company:
                findings.append(
                    {
                        "pair_id": item["pair_id"],
                        "kind": "foreign_company_evidence",
                        "value": evidence["source_id"],
                    }
                )
        text = " ".join(
            claim["text"]
            for section in (
                "facts",
                "bank_view",
                "ai_interpretation",
                "risks",
                "opportunities",
                "actions",
                "mechanism",
                "assumptions",
            )
            for claim in envelope["result"].get(section) or []
        ) + " ".join(envelope["result"]["unknowns"])
        for found in set(COMPANY_ID.findall(text)):
            findings.append(
                {"pair_id": item["pair_id"], "kind": "company_identifier_in_text", "value": found}
            )
    return findings


def judge_summary(run_dir: Path) -> dict:
    claims = []
    for path in sorted((run_dir / "judge").glob("*.json")) if (run_dir / "judge").exists() else []:
        record = read(path)
        for claim in record["claims"]:
            claims.append({**claim, "pair_id": path.stem})
    critical = [
        item for item in claims if item["section"] in CRITICAL_SECTIONS and item["verdict"] != "supported"
    ]
    bank = [
        item
        for item in claims
        if item["section"] == "bank_view" and item["verdict"] in {"unsupported", "contradicted"}
    ]
    by_section: dict[str, dict] = {}
    for section in sorted({item["section"] for item in claims}):
        by_section[section] = grounded_rate([item for item in claims if item["section"] == section])
    return {
        "overall": grounded_rate(claims),
        "by_section": by_section,
        "not_judged": sum(1 for item in claims if item["verdict"] == "not_judged"),
        "critical_unsupported_facts": critical,
        "false_bank_positions": bank,
        "unsupported_examples": [item for item in claims if item["verdict"] != "supported"][:20],
    }


def stems_of(claims: list[dict]) -> set[str]:
    return context_stems(" ".join(item["text"] for item in claims))


def jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left | right else 1.0


def difference_rates(
    pairs: dict, events: list[dict], left_context: str, right_context: str, threshold: float = 0.8
) -> dict:
    compared = different = 0
    for event in events:
        left, right = (
            pairs.get(pair_id(left_context, event["id"])),
            pairs.get(pair_id(right_context, event["id"])),
        )
        if not left or not right or left["status"] != "ok" or right["status"] != "ok":
            continue
        a, b = left["envelope"]["result"], right["envelope"]["result"]
        if not a["mechanism"] or not b["mechanism"]:
            continue
        compared += 1
        if jaccard(stems_of(a["mechanism"]), stems_of(b["mechanism"])) < threshold:
            different += 1
    return {
        "events_compared": compared,
        "different": different,
        "rate": round(different / compared, 4) if compared else None,
        "threshold": threshold,
    }


def behaviours(pairs: dict, events: list[dict], contexts: list[BenchmarkContext]) -> dict:
    ids = {item.context_id for item in contexts}
    result = {}
    if {"B01-chief_accountant", "B01-procurement_director"} <= ids:
        result["role_difference_same_company"] = difference_rates(
            pairs, events, "B01-chief_accountant", "B01-procurement_director"
        )
    if {"B01-chief_accountant", "B02-finance_director"} <= ids:
        result["credit_vs_non_credit_same_industry"] = difference_rates(
            pairs, events, "B01-chief_accountant", "B02-finance_director"
        )
    undetermined = [
        item
        for item in pairs.values()
        if item["status"] == "ok" and item["envelope"]["result"]["impact_level"] == "undetermined"
    ]
    result["undetermined_cards"] = {
        "count": len(undetermined),
        "without_unknowns": sum(1 for item in undetermined if not item["envelope"]["result"]["unknowns"]),
        "with_summary_but_not_labelled_hypothesis": sum(
            1
            for item in undetermined
            if item["envelope"]["result"]["personalized_summary"]
            and item["envelope"]["result"]["personalized_summary"]["statement_type"] != "hypothesis"
        ),
    }
    result["long_term_cards"] = sum(
        1
        for item in pairs.values()
        if item["status"] == "ok" and item["envelope"]["trace"]["impact"]["horizon_kind"] == "long_term"
    )
    result["dated_horizon_cards"] = sum(
        1
        for item in pairs.values()
        if item["status"] == "ok" and item["envelope"]["trace"]["impact"]["horizon_kind"] == "dated"
    )
    result["additional_search_cards"] = sum(
        1
        for item in pairs.values()
        if item["status"] == "ok" and item["envelope"]["trace"].get("extra_searches", 0) > 0
    )
    statuses: dict[str, int] = {}
    for item in pairs.values():
        if item["status"] == "ok":
            status = item["envelope"]["result"]["bank_view_context"]["status"]
            statuses[status] = statuses.get(status, 0) + 1
    result["bank_view_context"] = dict(sorted(statuses.items()))
    return result


def build_metrics(
    run_dir: Path, labels_dir: Path, contexts: list[BenchmarkContext], events: list[dict]
) -> dict:
    pairs = load_pairs(run_dir)
    all_ids = [pair_id(context.context_id, event["id"]) for context in contexts for event in events]
    label_sets = load_label_sets(labels_dir)
    adjudicated = adjudicate(label_sets, all_ids) if label_sets else {}
    labeled = bool(label_sets)
    lookup = {context.context_id: context for context in contexts}
    return {
        "run": read(run_dir / "run.json"),
        "cards": card_stats(pairs),
        "labels": {
            "labelers": agreement_report(label_sets) if labeled else None,
            "agreed": sum(1 for item in adjudicated.values() if item["status"] == "agreed"),
            "disputed": sum(1 for item in adjudicated.values() if item["status"] == "disputed"),
            "unlabeled": sum(1 for item in adjudicated.values() if item["status"] == "unlabeled"),
        },
        "ranking": ranking_metrics(run_dir, contexts, events, pairs, adjudicated, False)
        if labeled
        else "N/A: независимая разметка не получена",
        "ranking_sensitivity_disputed_as_significant": ranking_metrics(
            run_dir, contexts, events, pairs, adjudicated, True
        )
        if labeled
        else "N/A",
        "grounded_claims": judge_summary(run_dir),
        "leaks": leak_findings(pairs, lookup),
        "behaviours": behaviours(pairs, events, contexts),
    }

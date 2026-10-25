import math

GAINS = {0: 0, 1: 1, 2: 3}
K = 5
SIGNIFICANT = 2


def dcg(labels: list[int], k: int = K) -> float:
    return sum(GAINS[label] / math.log2(position + 2) for position, label in enumerate(labels[:k]))


def order_v2(scores: dict[str, float]) -> list[str]:
    return sorted(scores, key=lambda key: (-scores[key], key))


def context_result(shown: list[str], labels: dict[str, int], k: int = K) -> dict:
    top = shown[:k]
    gains = [labels.get(item, 0) for item in top]
    unlabeled = sum(1 for item in top if item not in labels)
    ideal = sorted(labels.values(), reverse=True)
    idcg = dcg(ideal, k)
    value = dcg(gains, k)
    significant = [item for item, label in labels.items() if label == SIGNIFICANT]
    hits = sum(1 for item in top if labels.get(item) == SIGNIFICANT)
    return {
        "top": top,
        "returned": len(top),
        "unlabeled_in_top": unlabeled,
        "dcg": round(value, 6),
        "idcg": round(idcg, 6),
        "ndcg": round(value / idcg, 4) if idcg else None,
        "hits": hits,
        "significant": len(significant),
        "recall": round(hits / len(significant), 4) if significant else None,
        "precision": round(hits / k, 4),
        "precision_ceiling": round(min(k, len(significant)) / k, 4),
    }


def aggregate_v2(rows: list[dict]) -> dict:
    defined = [item for item in rows if item["ndcg"] is not None]
    recall_rows = [item for item in rows if item["recall"] is not None]
    hits = sum(item["hits"] for item in recall_rows)
    available = sum(item["significant"] for item in recall_rows)
    total_idcg = sum(item["idcg"] for item in defined)
    total_dcg = sum(item["dcg"] for item in defined)
    precision_hits = sum(item["hits"] for item in rows)
    return {
        "contexts": len(rows),
        "unlabeled_in_top": sum(item["unlabeled_in_top"] for item in rows),
        "ndcg_defined": len(defined),
        "ndcg_na": len(rows) - len(defined),
        "ndcg_macro": round(sum(item["ndcg"] for item in defined) / len(defined), 4) if defined else None,
        "ndcg_pooled": round(total_dcg / total_idcg, 4) if total_idcg else None,
        "ndcg_pooled_numerator": round(total_dcg, 6),
        "ndcg_pooled_denominator": round(total_idcg, 6),
        "recall_defined": len(recall_rows),
        "recall_na": len(rows) - len(recall_rows),
        "recall_micro": round(hits / available, 4) if available else None,
        "recall_micro_numerator": hits,
        "recall_micro_denominator": available,
        "recall_macro": (
            round(sum(item["recall"] for item in recall_rows) / len(recall_rows), 4) if recall_rows else None
        ),
        "precision_micro": round(precision_hits / (K * len(rows)), 4) if rows else None,
        "precision_ceiling_micro": (
            round(sum(item["precision_ceiling"] for item in rows) / len(rows), 4) if rows else None
        ),
    }


def compare(candidate: dict[str, dict], baseline: dict[str, dict]) -> dict:
    new, old = aggregate_v2(list(candidate.values())), aggregate_v2(list(baseline.values()))
    diffs = {
        name: None if new[name] is None or old[name] is None else round(new[name] - old[name], 4)
        for name in ("ndcg_macro", "ndcg_pooled", "recall_micro", "recall_macro")
    }
    comparable = [
        key for key in candidate if candidate[key]["ndcg"] is not None and baseline[key]["ndcg"] is not None
    ]
    not_worse = [key for key in comparable if candidate[key]["ndcg"] >= baseline[key]["ndcg"]]
    return {
        "differences": diffs,
        "contexts_not_worse": len(not_worse),
        "contexts_compared": len(comparable),
        "share_not_worse": round(len(not_worse) / len(comparable), 4) if comparable else None,
    }


def gates(candidate: dict, comparison: dict, targets: dict, complete: bool = True) -> dict:
    checks = {
        "ndcg_macro": (candidate["ndcg_macro"], ">=", targets["ndcg_macro"]),
        "ndcg_pooled": (candidate["ndcg_pooled"], ">=", targets["ndcg_pooled"]),
        "recall_micro": (candidate["recall_micro"], ">=", targets["recall_micro"]),
        "recall_macro": (candidate["recall_macro"], ">=", targets["recall_macro"]),
        "share_not_worse": (comparison["share_not_worse"], ">=", targets["share_not_worse"]),
    }
    result = {}
    for name, (value, _, limit) in checks.items():
        result[name] = {"value": value, "threshold": limit, "passed": value is not None and value >= limit}
    for name, value in comparison["differences"].items():
        result[f"diff_{name}"] = {"value": value, "threshold": 0, "passed": value is not None and value >= 0}
    result["sufficient"] = {
        "ndcg_defined": candidate["ndcg_defined"],
        "recall_defined": candidate["recall_defined"],
        "passed": candidate["ndcg_defined"] >= targets["min_ndcg_contexts"]
        and candidate["recall_defined"] >= targets["min_recall_contexts"],
    }
    result["labels_complete"] = {"value": complete, "threshold": True, "passed": complete}
    result["status"] = "COMPLETE" if complete else "INCOMPLETE"
    result["passed"] = complete and all(
        item["passed"] for key, item in result.items() if isinstance(item, dict)
    )
    return result

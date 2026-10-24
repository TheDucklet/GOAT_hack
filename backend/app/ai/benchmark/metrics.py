from app.ai.benchmark.labels import SIGNIFICANT

K = 5
IMPACT_ORDER = {"high": 3, "medium": 2, "low": 1, "undetermined": 0}


def precision_recall_at_k(ranking: list[str], significant: set[str], pool: set[str], k: int = K) -> dict:
    pool_significant = significant & pool
    top = [item for item in ranking if item in pool][:k]
    hits = sum(1 for item in top if item in pool_significant)
    return {
        "k": k,
        "returned": len(top),
        "hits": hits,
        "significant_in_pool": len(pool_significant),
        "precision": round(hits / k, 4) if len(top) >= k else None,
        "recall": round(hits / len(pool_significant), 4) if pool_significant else None,
    }


def aggregate(per_context: list[dict]) -> dict:
    precision = [item["precision"] for item in per_context if item["precision"] is not None]
    recall = [item["recall"] for item in per_context if item["recall"] is not None]
    hits = sum(item["hits"] for item in per_context if item["precision"] is not None)
    slots = sum(item["k"] for item in per_context if item["precision"] is not None)
    found = sum(item["hits"] for item in per_context if item["recall"] is not None)
    available = sum(item["significant_in_pool"] for item in per_context if item["recall"] is not None)
    ceiling = sum(
        min(item["significant_in_pool"], item["k"]) for item in per_context if item["precision"] is not None
    )
    return {
        "contexts": len(per_context),
        "precision_macro": round(sum(precision) / len(precision), 4) if precision else None,
        "precision_micro": round(hits / slots, 4) if slots else None,
        "precision_numerator": hits,
        "precision_denominator": slots,
        "precision_ceiling_numerator": ceiling,
        "precision_ceiling_micro": round(ceiling / slots, 4) if slots else None,
        "recall_macro": round(sum(recall) / len(recall), 4) if recall else None,
        "recall_micro": round(found / available, 4) if available else None,
        "recall_numerator": found,
        "recall_denominator": available,
        "precision_na_contexts": len(per_context) - len(precision),
        "recall_na_contexts": len(per_context) - len(recall),
    }


def significant_pairs(adjudicated: dict[str, dict], include_disputed: bool = False) -> set[str]:
    return {
        pair
        for pair, item in adjudicated.items()
        if item["final"] == SIGNIFICANT or (include_disputed and item["any_significant"])
    }


def labeled_pairs(adjudicated: dict[str, dict], include_disputed: bool = False) -> set[str]:
    return {
        pair
        for pair, item in adjudicated.items()
        if item["status"] == "agreed" or (include_disputed and item["status"] == "disputed")
    }


def grounded_rate(claims: list[dict]) -> dict:
    total = len(claims)
    grounded = sum(1 for claim in claims if claim["grounded"])
    return {
        "claims": total,
        "grounded": grounded,
        "rate": round(grounded / total, 4) if total else None,
    }

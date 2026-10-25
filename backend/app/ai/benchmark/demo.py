import json
from collections import Counter
from pathlib import Path

from app.ai.benchmark.data import load_events
from app.ai.benchmark.runner import read

DEFAULT_PAIR = "B01-procurement_director__ev-syn-inflation-weekly"
TRACE_TOOLS = {"get_company_context", "get_event", "search_bank_analytics"}


def chunk_index(snapshot: Path) -> dict[str, dict]:
    return {item["chunk_id"]: item for item in json.loads(snapshot.read_text(encoding="utf-8"))}


def fragments(returned: list[dict], index: dict[str, dict]) -> list[dict]:
    result = []
    for item in returned:
        chunk = index.get(item["chunk_id"], {})
        result.append(
            {
                "document": chunk.get("filename"),
                "document_date": chunk.get("document_date"),
                "page": item.get("page"),
                "historical": item.get("historical"),
            }
        )
    return result


def trace_steps(trace: dict, index: dict[str, dict]) -> list[dict]:
    steps = []
    for step in trace["steps"]:
        if step.get("tool") == "search_bank_analytics":
            steps.append(
                {
                    "step": "search",
                    "purpose": step["purpose"],
                    "query": step["query"],
                    "as_of": step["as_of"],
                    "fragments": fragments(step["returned"], index),
                    "empty_reason": step.get("empty_reason"),
                }
            )
        elif "plan" in step and "initial_queries" in step:
            steps.append({"step": "plan", "topics": step["plan"], "initial_queries": step["initial_queries"]})
        elif "check" in step:
            steps.append({"step": "check", "iteration": step["iteration"], "verdict": step["check"]})
        elif "retry" in step:
            steps.append(
                {
                    "step": "retry",
                    "previous_queries": step["previous_queries"],
                    "new_query": step["new_query"],
                    "reason": step["reason"],
                }
            )
        elif "stop" in step:
            steps.append(
                {
                    "step": "stop",
                    "reason": step["stop"],
                    "iterations": step["iterations"],
                    "extra_searches": step["extra_searches"],
                }
            )
    return steps


def usage_summary(record: dict, trace: dict) -> dict:
    calls = Counter(step["llm"] for step in trace["steps"] if "llm" in step)
    return {
        "llm_calls": dict(calls),
        "cost_rub": record["cost_rub"],
        "latency_seconds": record["latency_seconds"],
    }


def rejected_claims(trace: dict) -> list[dict]:
    return [
        {"text": claim["text"], "verdict": claim["verdict"], "reason": claim["reason"]}
        for check in trace["checks"]
        for claim in check.get("rejected_bank_claims", [])
    ]


def selection_note(run_dir: Path, pair: str) -> dict:
    matching = []
    for path in sorted((run_dir / "pairs").glob("*.json")):
        record = read(path)
        result, trace = record["envelope"]["result"], record["envelope"]["trace"]
        if result["bank_view"] and trace.get("extra_searches", 0) >= 1:
            matching.append(record["pair_id"])
    return {
        "criteria": "карточка с позицией банка, подтверждённой после дополнительного поиска",
        "cards_total": len(list((run_dir / "pairs").glob("*.json"))),
        "cards_matching": len(matching),
        "chosen": pair,
        "chosen_reason": "из подходящих карточек у неё нет утверждений фактов и банка с вердиктом судьи, отличным от supported",
    }


def build_demo(run_dir: Path, pair: str, snapshot: Path, directory: Path) -> dict:
    record = read(run_dir / "pairs" / f"{pair}.json")
    envelope = record["envelope"]
    result, trace = envelope["result"], envelope["trace"]
    judged = read(run_dir / "judge" / f"{pair}.json")["claims"]
    metrics = read(run_dir / "metrics.json")
    source = read(run_dir / "run.json")["source"]
    event = next(item for item in load_events(directory) if item["id"] == record["event_id"])
    index = chunk_index(snapshot)
    evidence = {item["id"]: item for item in envelope["evidence"]}
    return {
        "title": "Агентная трасса v2: отклонённая позиция банка и уточнённый поиск",
        "source_sha": source["sha"],
        "run": str(run_dir.name),
        "pair_id": pair,
        "note": (
            "Одна карточка из прогона F-16 на офлайн-снимке материалов банка. Профиль компании и новость синтетические, "
            "страницы, даты и цитаты материалов банка настоящие."
        ),
        "input": {
            "context_id": record["context_id"],
            "event_id": event["id"],
            "event_title": event["title"],
            "event_source": event["source"],
        },
        "steps": trace_steps(trace, index),
        "rejected_bank_claims": rejected_claims(trace),
        "bank_view": [
            {
                "text": claim["text"],
                "sources": [
                    {
                        "document": evidence[ref]["locator"].get("title"),
                        "document_date": evidence[ref]["locator"].get("document_date"),
                        "page": evidence[ref]["locator"].get("page"),
                        "quote": evidence[ref]["excerpt"],
                    }
                    for ref in claim["evidence_refs"]
                ],
            }
            for claim in result["bank_view"]
        ],
        "bank_view_context": result["bank_view_context"],
        "impact": {
            "level": result["impact_level"],
            "reason": result["impact_reason"]["text"] if result["impact_reason"] else None,
            "mechanism_steps": len(result["mechanism"]),
            "horizon_kind": trace["impact"]["horizon_kind"],
        },
        "unknowns": result["unknowns"],
        "usage": usage_summary(record, trace),
        "judge": {
            "claims": len(judged),
            "supported": sum(1 for item in judged if item["grounded"]),
            "not_supported_sections": sorted({item["section"] for item in judged if not item["grounded"]}),
        },
        "selection": selection_note(run_dir, pair),
        "limitations": {
            "benchmark": "docs/quality/insight-v2-evaluation.md",
            "grounded_claims_rate": metrics["grounded_claims"]["overall"]["rate"],
            "cards": metrics["cards"]["ok"],
            "llm_variability": (
                "генерация нестабильна: повтор запуска даёт другие запросы и другую позицию банка, "
                "в повторной приёмке S7 агент уточнил запрос, но позиция банка не подтвердилась"
            ),
            "search": "офлайн-снимок docs/ai/fixtures/bank-chunks.json, не PostgreSQL",
        },
    }

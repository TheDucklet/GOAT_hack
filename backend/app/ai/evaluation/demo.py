import json
from pathlib import Path

PREVIEW_CHARS = 400


def shorten(text: str, limit: int = PREVIEW_CHARS) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3].rsplit(" ", 1)[0] + "..."


def compact_step(step: dict, checks: list[dict]) -> dict | None:
    if step.get("tool") == "search_bank_analytics":
        return {
            "step": "search",
            "purpose": step["purpose"],
            "query": step["query"],
            "as_of": step["as_of"],
            "fragments": [
                {"page": item["page"], "historical": item["historical"]} for item in step["returned"]
            ],
            "note": step.get("empty_reason"),
        }
    if "check" in step:
        record = checks[step["iteration"] - 1]
        return {
            "step": "check",
            "iteration": step["iteration"],
            "status": step["check"],
            "reasons": [item["code"] for item in step["reasons"]],
            "rejected_bank_claims": [
                {"text": shorten(item.get("text", ""), 200), "reason": item["reason"]}
                for item in record.get("rejected_bank_claims", [])
            ],
        }
    if "retry" in step:
        return {
            "step": "retry",
            "number": step["retry"],
            "tried_queries": len(step["previous_queries"]),
            "new_query": step["new_query"],
            "reason": step["reason"],
        }
    if "stop" in step:
        return {
            "step": "stop",
            "reason": step["stop"],
            "iterations": step["iterations"],
            "extra_searches": step["extra_searches"],
        }
    return None


def usage_of(steps: list[dict]) -> dict:
    calls: dict[str, int] = {}
    for step in steps:
        if "llm" in step:
            calls[step["llm"]] = calls.get(step["llm"], 0) + 1
    cost = sum(step.get("cost_rub", 0) for step in steps if "llm" in step)
    return {"llm_calls": calls, "cost_rub": round(cost, 4)}


def build_demo(scenario: dict, summary: dict, document_names: dict[str, str]) -> dict:
    card = scenario["cards"][0]
    envelope = card["envelope"]
    trace = envelope["trace"]
    evidence = {item["id"]: item for item in envelope["evidence"]}
    steps = [item for step in trace["steps"] if (item := compact_step(step, trace["checks"]))]
    bank_view = [
        {
            "claim_id": claim["claim_id"],
            "text": claim["text"],
            "evidence": [
                {
                    "id": ref,
                    "document": document_names.get(evidence[ref]["source_id"], evidence[ref]["source_id"]),
                    "page": evidence[ref]["locator"]["page"],
                    "excerpt": shorten(evidence[ref]["excerpt"]),
                }
                for ref in claim["evidence_refs"]
            ],
        }
        for claim in envelope["result"]["bank_view"] or []
    ]
    return {
        "title": "Повторный поиск материалов банка",
        "note": "Синтетическая новость. Результаты первых двух поисков скрыты, чтобы показать собственную логику "
        "агента при отсутствии первого evidence. Фрагменты, цитаты и страницы настоящие.",
        "source_sha": summary["source_sha"],
        "input": {
            "scenario": scenario["id"],
            "company_id": card["company_id"],
            "position": card["position"],
            "event_summary": card["summary"]["summary"],
            "focus_topics": card["focus"]["topics"],
        },
        "plan": trace["plan"],
        "steps": steps,
        "bank_view": bank_view,
        "unknowns": envelope["result"]["unknowns"],
        "usage": usage_of(trace["steps"]),
    }


def write_demo(acceptance: Path, chunks_path: Path, output: Path) -> dict:
    scenario = json.loads((acceptance / "S7.json").read_text(encoding="utf-8"))
    summary = json.loads((acceptance / "summary.json").read_text(encoding="utf-8"))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    names = {chunk["document_id"]: chunk["filename"] for chunk in chunks}
    demo = build_demo(scenario, summary, names)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(demo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return demo

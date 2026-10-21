import argparse
import json
import sys
from pathlib import Path

from app.ai.agent.runner import run_agent
from app.ai.insights.local_tools import LocalTools, repository_search
from app.ai.providers import LLMError
from app.ai.rag.file_repository import FileRepository

SCENARIOS = {
    "ordinary": {
        "title": "обычный сценарий: материалы банка найдены первым поиском",
        "event": "key_rate_pause",
        "company": "U_38174",
        "position": "chief_accountant",
        "suppressed_searches": 0,
    },
    "repeat-search": {
        "title": "повторный поиск: первые запросы ничего не вернули",
        "event": "key_rate_pause",
        "company": "U_9085",
        "position": "chief_accountant",
        "suppressed_searches": 2,
    },
    "retry-limit": {
        "title": "предел повторов: по теме нет материалов банка",
        "event": "steel_export_duty",
        "company": "U_243",
        "position": "procurement_director",
        "suppressed_searches": 0,
    },
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def suppressing(search, count: int):
    state = {"left": count}

    def wrapped(query: str, as_of: str, limit: int) -> dict:
        if state["left"] > 0:
            state["left"] -= 1
            return {
                "items": [],
                "query": query,
                "as_of": as_of,
                "empty_reason": "результат скрыт в сценарии отсутствия первого evidence",
            }
        return search(query, as_of, limit)

    return wrapped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.agent")
    parser.add_argument("scenario", choices=[*SCENARIOS, "all"])
    parser.add_argument("--fixtures", default="../docs/ai/fixtures")
    parser.add_argument("--summaries", default="../docs/ai/summary-checks.json")
    parser.add_argument("--focus", default="../docs/ai/focus-checks.json")
    parser.add_argument("--output-dir", default="../docs/ai/agent-traces")
    args = parser.parse_args(argv)
    fixtures = Path(args.fixtures)
    companies = {item["company_id"]: item for item in load(fixtures / "companies.json")}
    summaries = {item["name"]: item for item in load(Path(args.summaries))}
    focuses = {item["name"]: item["result"] for item in load(Path(args.focus))}
    repository = FileRepository(fixtures / "bank-chunks.json")
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        for name in names:
            case = SCENARIOS[name]
            summary = summaries[case["event"]]
            event = {
                **summary["input"],
                "summary": summary["result"]["summary"],
                "facts": summary["result"]["facts"],
                "topics": summary["result"]["topics"],
            }
            context = companies[case["company"]]
            search = suppressing(repository_search(repository), case["suppressed_searches"])
            envelope = run_agent(
                context, focuses[case["position"]], event, LocalTools(context, event, search)
            )
            document = {
                "scenario": name,
                "title": case["title"],
                "company": case["company"],
                "event": case["event"],
                "envelope": envelope,
            }
            target = out / f"{name}.json"
            target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            trace = envelope["trace"]
            print(
                name,
                trace["stop_reason"],
                "iterations",
                trace["iterations"],
                "extra_searches",
                trace["extra_searches"],
            )
    except LLMError as error:
        print(f"Сценарий остановлен: {error.code} – {error.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

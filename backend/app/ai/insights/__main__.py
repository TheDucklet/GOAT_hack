import argparse
import json
import os
import sys
from pathlib import Path

from app.ai.insights.build import SEARCH_LIMIT, build_insight, event_date, search_queries
from app.ai.insights.local_tools import LocalTools, SearchSnapshot, repository_search
from app.ai.providers import LLMError
from app.ai.schemas import EventPayload

CASES = [
    {
        "name": "key_rate_company_with_loan",
        "event": "key_rate_pause",
        "company": "U_38174",
        "position": "chief_accountant",
    },
    {
        "name": "key_rate_company_without_loan",
        "event": "key_rate_pause",
        "company": "U_9085",
        "position": "chief_accountant",
    },
    {
        "name": "steel_duty_company_trading_with_china",
        "event": "steel_export_duty",
        "company": "U_243",
        "position": "procurement_director",
    },
    {
        "name": "steel_duty_domestic_company",
        "event": "steel_export_duty",
        "company": "U_2883",
        "position": "procurement_director",
    },
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def case_event(case: dict, summaries: dict) -> dict:
    summary = summaries[case["event"]]
    return {
        **summary["input"],
        "summary": summary["result"]["summary"],
        "facts": summary["result"]["facts"],
        "topics": summary["result"]["topics"],
    }


def record_searches(args: argparse.Namespace, search_for) -> int:
    summaries = {item["name"]: item for item in load(Path(args.summaries))}
    count = 0
    for case in CASES:
        event = EventPayload.model_validate(case_event(case, summaries))
        for query in search_queries(event):
            search_for(query, event_date(event).isoformat(), SEARCH_LIMIT)
            count += 1
    return count


def run_cases(args: argparse.Namespace, search_for) -> list[dict]:
    fixtures = Path(args.fixtures)
    companies = {item["company_id"]: item for item in load(fixtures / "companies.json")}
    summaries = {item["name"]: item for item in load(Path(args.summaries))}
    focuses = {item["name"]: item["result"] for item in load(Path(args.focus))}
    results = []
    for case in CASES:
        event = case_event(case, summaries)
        context = companies[case["company"]]
        tools = LocalTools(context, event, search_for)
        envelope = build_insight(context, focuses[case["position"]], event, tools)
        results.append({**case, "envelope": envelope})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.insights")
    parser.add_argument("mode", choices=["snapshot", "generate"])
    parser.add_argument("--fixtures", default="../docs/ai/fixtures")
    parser.add_argument("--summaries", default="../docs/ai/summary-checks.json")
    parser.add_argument("--focus", default="../docs/ai/focus-checks.json")
    parser.add_argument("--snapshot", default="../docs/ai/fixtures/bank-search-snapshot.json")
    parser.add_argument("--output", default="../docs/ai/insight-examples.json")
    args = parser.parse_args(argv)
    os.environ.setdefault("AI_MODULE", "app.ai.bridge")
    snapshot = SearchSnapshot(Path(args.snapshot))
    try:
        if args.mode == "snapshot":
            from app.db import session_factory
            from app.services.tools import BankRepository

            with session_factory()() as db:
                count = record_searches(args, snapshot.recording(repository_search(BankRepository(db))))
            snapshot.save()
            print(f"запросов записано: {count}")
            return 0
        results = run_cases(args, snapshot.replay)
    except LLMError as error:
        print(f"Проверка остановлена: {error.code} – {error.message}", file=sys.stderr)
        return 1
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"карточек: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

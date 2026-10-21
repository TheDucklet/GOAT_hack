import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.ai.evaluation.demo import write_demo
from app.ai.evaluation.pipeline import DEFAULT_FIXTURES, DEFAULT_INPUTS, SearchLog, Workspace
from app.ai.evaluation.scenarios import SCENARIOS, Session
from app.ai.ocr.settings import OCR_PROMPT_VERSION, get_ocr_settings
from app.ai.providers import LLMError
from app.ai.rag.search import search_bank_analytics

OCR_CONTROLS = {
    "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf": (1, ["14,0%", "13,7%", "23 октября"]),
    "Inflation_tracker_02.pdf": (1, ["0,08%", "4,67%", "6,32%"]),
    "Gold_digest_August26.pdf": (2, ["4 650", "4,1%", "162 тысячи"]),
    "ALFA-7M26.pdf": (2, ["9,6%", "12,7%", "74,8"]),
    "FI_Strategy_3Q26_22072026.pdf": (10, ["13,7%", "102 трлн", "2,5 раза"]),
}


def source_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def tree_is_dirty() -> bool:
    try:
        return bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--", ".", "../docs/ai", "../docs/quality/fixtures"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return True


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_scenarios(args: argparse.Namespace) -> int:
    workspace = Workspace(Path(args.fixtures), Path(args.inputs))
    session = Session(workspace)
    output = Path(args.output)
    selected = args.only or list(SCENARIOS)
    results = []
    try:
        for scenario_id in selected:
            result = SCENARIOS[scenario_id](session)
            write(output / f"{scenario_id}.json", result)
            results.append(result)
            failed = [
                item["name"]
                for item in [
                    *[x for card in result["cards"] for x in card["checks"]],
                    *result["extra_checks"],
                ]
                if not item["ok"]
            ]
            print(f"{scenario_id} {result['verdict']} {result['title']} {failed or ''}")
    except LLMError as error:
        print(f"Проверка остановлена: {error.code} – {error.message}", file=sys.stderr)
        return 1
    if not args.only:
        write(
            output / "summary.json",
            {
                "checked_at": datetime.now(UTC).date().isoformat(),
                "source_sha": source_sha(),
                "tree_clean": not tree_is_dirty(),
                "scenarios": [{"id": r["id"], "title": r["title"], "verdict": r["verdict"]} for r in results],
            },
        )
    return 0 if all(r["verdict"] == "PASS" for r in results) else 2


def replay_search(args: argparse.Namespace) -> int:
    workspace = Workspace(Path(args.fixtures), Path(args.inputs))
    saved = json.loads((Path(args.output) / f"{args.scenario}.json").read_text(encoding="utf-8"))
    mismatches = 0
    total = 0
    for card in saved["cards"]:
        for call in card["searches"]:
            if call.get("suppressed"):
                print(f"скрыт в сценарии: {call['query']}")
                continue
            log = SearchLog(workspace.search)
            log(call["query"], call["as_of"], call["limit"])
            same = log.calls[0]["chunk_ids"] == call["chunk_ids"]
            total += 1
            mismatches += 0 if same else 1
            print(
                f"{'совпало' if same else 'РАСХОЖДЕНИЕ'}: {call['query']} ({len(call['chunk_ids'])} фрагментов)"
            )
    print(f"запросов: {total}, расхождений: {mismatches}")
    return 1 if mismatches else 0


def check_retrieval(args: argparse.Namespace) -> int:
    workspace = Workspace(Path(args.fixtures), Path(args.inputs))
    repository = workspace.repository
    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    chunks = json.loads(workspace.chunks_path.read_text(encoding="utf-8"))
    names = {chunk["document_id"]: chunk["filename"] for chunk in chunks}
    records = []
    for item in queries:
        found = search_bank_analytics(item["query"], item["as_of"], 5, repository)
        top = [{"file": names[hit["document_id"]], "page": hit["page"]} for hit in found["items"]]
        expected = item["expected"]
        ranks = [index + 1 for index, hit in enumerate(top) if hit in expected]
        passed = bool(ranks) if expected else not top
        records.append(
            {
                "id": item["id"],
                "query": item["query"],
                "expected": expected,
                "result": "PASS" if passed else "FAIL",
                "first_expected_rank": ranks[0] if ranks else None,
                "returned": top,
                "empty_reason": found.get("empty_reason"),
            }
        )
        print(f"{item['id']} {records[-1]['result']}")
    report = {
        "checked_at": datetime.now(UTC).date().isoformat(),
        "source_sha": source_sha(),
        "tree_clean": not tree_is_dirty(),
        "repository": "снимок docs/ai/fixtures/bank-chunks.json",
        "passed": sum(1 for r in records if r["result"] == "PASS"),
        "total": len(records),
        "queries": records,
    }
    write(Path(args.output) / "retrieval.json", report)
    return 0 if report["passed"] == report["total"] else 2


def check_ocr(args: argparse.Namespace) -> int:
    ocr_report = json.loads(Path(args.ocr_report).read_text(encoding="utf-8"))
    sha_of = {item["file"]: item["sha256"] for item in ocr_report["documents"]}
    cache_dir = get_ocr_settings().cache_dir
    records = []
    for file_name, (page, controls) in OCR_CONTROLS.items():
        path = cache_dir / sha_of[file_name] / f"{OCR_PROMPT_VERSION}-p{page:03d}.json"
        text = json.loads(path.read_text(encoding="utf-8"))["text"] if path.exists() else ""
        missing = [token for token in controls if token not in text]
        records.append(
            {
                "file": file_name,
                "page": page,
                "characters": len(text),
                "controls": controls,
                "missing": missing,
                "result": "PASS" if text and not missing else "FAIL",
            }
        )
        print(f"{file_name} с.{page} {records[-1]['result']}")
    report = {
        "checked_at": datetime.now(UTC).date().isoformat(),
        "source_sha": source_sha(),
        "tree_clean": not tree_is_dirty(),
        "prompt_version": OCR_PROMPT_VERSION,
        "passed": sum(1 for r in records if r["result"] == "PASS"),
        "total": len(records),
        "pages": records,
    }
    write(Path(args.output) / "ocr.json", report)
    return 0 if report["passed"] == report["total"] else 2


def build_demo_trace(args: argparse.Namespace) -> int:
    demo = write_demo(Path(args.output), Path(args.fixtures) / "bank-chunks.json", Path(args.demo_output))
    print(f"шагов: {len(demo['steps'])}, утверждений банка: {len(demo['bank_view'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.evaluation")
    parser.add_argument("command", choices=["run", "search", "retrieval", "ocr", "demo"])
    parser.add_argument("--only", nargs="*", choices=list(SCENARIOS))
    parser.add_argument("--scenario", default="S7")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    parser.add_argument("--inputs", default=str(DEFAULT_INPUTS))
    parser.add_argument("--queries", default="../docs/ai/retrieval-queries.json")
    parser.add_argument("--ocr-report", default="../docs/ai/ocr-report.json")
    parser.add_argument("--output", default="../docs/quality/acceptance")
    parser.add_argument("--demo-output", default="../docs/demo/agent-trace.json")
    args = parser.parse_args(argv)
    handlers = {
        "run": run_scenarios,
        "search": replay_search,
        "retrieval": check_retrieval,
        "ocr": check_ocr,
        "demo": build_demo_trace,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

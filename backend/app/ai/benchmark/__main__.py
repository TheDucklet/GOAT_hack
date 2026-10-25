import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.ai.benchmark.calibration import SEED, build_sheets
from app.ai.benchmark.data import DEFAULT_DIRECTORY, load_contexts, load_events, load_positions
from app.ai.benchmark.judge import judge_card
from app.ai.benchmark.labels import sheet_rows, write_sheet
from app.ai.benchmark.report import build_metrics, load_pairs
from app.ai.benchmark.runner import DEFAULT_FIXTURES, read, run_all, write
from app.ai.benchmark.targeted import run_targeted
from app.ai.benchmark.verifier_check import check_verifier
from app.ai.providers import LLMError

RUNS = Path("../docs/quality/benchmark/runs")


def prepare(args) -> int:
    directory = Path(args.directory)
    contexts, events = load_contexts(directory), load_events(directory)
    rows = sheet_rows(contexts, events, load_positions(directory))
    write_sheet(directory / "labeling" / "sheet.csv", rows)
    print(f"контекстов: {len(contexts)}, событий: {len(events)}, пар для разметки: {len(rows)}")
    return 0


def run(args) -> int:
    run_dir = RUNS / args.run_id
    only = set(args.only) if args.only else None
    summary = run_all(run_dir, Path(args.directory), DEFAULT_FIXTURES, args.workers, only)
    print(f"пар: {summary['pairs']}, ошибок: {summary['errors']}")
    return 0 if not summary["errors"] else 2


def judge(args) -> int:
    run_dir = RUNS / args.run_id
    pairs = {key: item for key, item in load_pairs(run_dir).items() if item["status"] == "ok"}
    publications = {
        publication["id"]: publication["text"]
        for event in read(run_dir / "events.json")
        for publication in event["publications"]
    }

    def work(key):
        path = run_dir / "judge" / f"{key}.json"
        if path.exists():
            return key
        write(path, judge_card(pairs[key]["envelope"], publications))
        return key

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        done = list(pool.map(work, sorted(pairs)))
    print(f"карточек проверено: {len(done)}")
    return 0


def targeted(args) -> int:
    run_dir = RUNS / args.run_id
    results = run_targeted(run_dir, load_contexts(Path(args.directory)), live=not args.offline)
    for name, item in results.items():
        print(f"{name}: {'PASS' if item['passed'] else 'FAIL'}")
    return 0 if all(item["passed"] for item in results.values()) else 2


def calibration(args) -> int:
    selection = build_sheets(RUNS / args.run_id, Path(args.directory) / "calibration", args.seed)
    print(
        f"критических вхождений: {selection['critical_occurrences']}, уникальных: {selection['critical_unique']}, "
        f"строк калибровки: {selection['calibration_rows']}, контроля: {selection['control_rows']}"
    )
    return 0


def verifier_check(args) -> int:
    base = Path(args.directory) / "calibration"
    report = check_verifier(base / f"{args.sheet}-sheet.csv", Path(args.labels), Path(args.output))
    print(
        f"строк: {report['rows']}, согласие: {report['agreement']}, kappa: {report['kappa_binary']}, "
        f"ложных supported: {report['false_supported']}, ложных unsupported: {report['false_unsupported']}"
    )
    return 0


def metrics(args) -> int:
    run_dir = RUNS / args.run_id
    directory = Path(args.directory)
    report = build_metrics(
        run_dir, directory / "labeling", load_contexts(directory), read(run_dir / "events.json")
    )
    if (run_dir / "targeted.json").exists():
        report["targeted"] = {
            name: {k: v for k, v in item.items() if k != "record"}
            for name, item in read(run_dir / "targeted.json").items()
        }
    write(run_dir / "metrics.json", report)
    print(f"метрики записаны: {run_dir / 'metrics.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.benchmark")
    parser.add_argument(
        "command", choices=["prepare", "run", "judge", "targeted", "metrics", "calibration", "verifier-check"]
    )
    parser.add_argument("--directory", default=str(DEFAULT_DIRECTORY))
    parser.add_argument("--run-id", default="run-1")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--sheet", default="calibration")
    parser.add_argument("--labels")
    parser.add_argument("--output", default="verifier-check.json")
    args = parser.parse_args(argv)
    handlers = {
        "prepare": prepare,
        "run": run,
        "judge": judge,
        "targeted": targeted,
        "metrics": metrics,
        "calibration": calibration,
        "verifier-check": verifier_check,
    }
    try:
        return handlers[args.command](args)
    except LLMError as error:
        print(f"Прогон остановлен: {error.code} – {error.message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

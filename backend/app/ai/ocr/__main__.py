import argparse
import json
import sys
from pathlib import Path

from app.ai.ocr.pipeline import OcrDocument, ocr_document
from app.ai.ocr.render import page_count
from app.ai.providers import LLMError


def parse_pages(value: str | None) -> list[int] | None:
    if not value:
        return None
    return [int(part) for part in value.split(",") if part.strip()]


def document_entry(recognized: OcrDocument) -> dict:
    ok_pages = [page for page in recognized.pages if page.status == "ok"]
    return {
        "file": recognized.path.name,
        "sha256": recognized.sha256,
        "pages": len(recognized.pages),
        "non_empty_pages": recognized.non_empty_pages,
        "failed_pages": [{"page": page.page, "reason": page.failure} for page in recognized.failed_pages],
        "title": recognized.title,
        "document_date": recognized.document_date.isoformat() if recognized.document_date else None,
        "date_unknown": recognized.date_unknown,
        "characters": sum(len(page.text) for page in ok_pages),
        "input_tokens": sum(page.input_tokens for page in recognized.pages),
        "output_tokens": sum(page.output_tokens for page in recognized.pages),
        "cost_rub": round(sum(page.cost_rub for page in recognized.pages), 4),
        "engine": sorted({page.engine for page in recognized.pages if page.engine}),
    }


def run_probe(args: argparse.Namespace) -> int:
    recognized = ocr_document(Path(args.pdf), pages=parse_pages(args.pages), use_cache=not args.refresh)
    for page in recognized.pages:
        print(f"=== страница {page.page} ({page.status}, {len(page.text)} симв.) ===")
        print(page.text if page.status == "ok" else f"ошибка: {page.failure}")
    print(json.dumps(document_entry(recognized), ensure_ascii=False, indent=2))
    return 0 if not recognized.failed_pages else 1


def run_report(args: argparse.Namespace) -> int:
    output = Path(args.output)
    previous = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    entries = [document_entry(ocr_document(path)) for path in sorted(Path(args.dir).glob("*.pdf"))]
    report = {
        "documents": entries,
        "totals": {
            "documents": len(entries),
            "pages": sum(entry["pages"] for entry in entries),
            "non_empty_pages": sum(entry["non_empty_pages"] for entry in entries),
            "failed_pages": sum(len(entry["failed_pages"]) for entry in entries),
            "input_tokens": sum(entry["input_tokens"] for entry in entries),
            "output_tokens": sum(entry["output_tokens"] for entry in entries),
            "cost_rub": round(sum(entry["cost_rub"] for entry in entries), 4),
        },
        "manual_checks": previous.get("manual_checks", []),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 0 if report["totals"]["failed_pages"] == 0 else 1


def run_count(args: argparse.Namespace) -> int:
    total = 0
    for path in sorted(Path(args.dir).glob("*.pdf")):
        count = page_count(path)
        total += count
        print(f"{path.name}\t{count}")
    print(f"всего\t{total}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.ocr")
    commands = parser.add_subparsers(dest="command", required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--pdf", required=True)
    probe.add_argument("--pages")
    probe.add_argument("--refresh", action="store_true")
    probe.set_defaults(run=run_probe)
    report = commands.add_parser("report")
    report.add_argument("--dir", required=True)
    report.add_argument("--output", default="../docs/ai/ocr-report.json")
    report.set_defaults(run=run_report)
    count = commands.add_parser("count")
    count.add_argument("--dir", required=True)
    count.set_defaults(run=run_count)
    args = parser.parse_args(argv)
    try:
        return args.run(args)
    except LLMError as error:
        print(f"Распознавание остановлено: {error.code} – {error.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

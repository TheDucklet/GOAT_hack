import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.ai.ocr.render import file_sha256, page_count
from app.ai.rag.search import search_bank_analytics
from app.integrations.ai import AIError

BRIDGE_MODULE = "app.ai.bridge"
TOP_RESULTS = 5


def prepare_environment() -> None:
    os.environ.setdefault("AI_MODULE", BRIDGE_MODULE)
    from app.config import get_settings
    from app.db import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()


def register_pdfs(db, directory: Path) -> list:
    from app.config import get_settings
    from app.models import BankDocument

    storage = get_settings().storage_dir
    storage.mkdir(parents=True, exist_ok=True)
    documents = []
    for path in sorted(directory.glob("*.pdf")):
        sha = file_sha256(path)
        document = db.scalar(select(BankDocument).where(BankDocument.sha256 == sha))
        if document is None:
            target = storage / f"{sha}.pdf"
            if not target.exists():
                shutil.copyfile(path, target)
            document = BankDocument(
                filename=path.name,
                sha256=sha,
                version=sha,
                storage_key=target.name,
                page_count=page_count(path),
            )
            db.add(document)
            db.flush()
        documents.append(document)
    return documents


def run_reindex(args: argparse.Namespace) -> int:
    prepare_environment()
    from app.cli import migrate
    from app.db import session_factory
    from app.models import BankDocument
    from app.services.job_handlers.documents import ingest_document_job

    if args.migrate:
        migrate()
    failures = 0
    with session_factory()() as db, db.begin():
        if args.pdf_dir:
            register_pdfs(db, Path(args.pdf_dir))
        documents = list(db.scalars(select(BankDocument).order_by(BankDocument.filename)))
    for document in documents:
        if args.document_id and document.id != args.document_id:
            continue
        try:
            with session_factory()() as db, db.begin():
                result = ingest_document_job(db, SimpleNamespace(payload={"document_id": document.id}))
            print(f"{document.filename}: фрагментов {result['chunks']}")
        except AIError as error:
            failures += 1
            print(f"{document.filename}: ошибка {error.code} – {error.message}", file=sys.stderr)
    return 1 if failures else 0


def run_check(args: argparse.Namespace) -> int:
    prepare_environment()
    from app.db import session_factory
    from app.models import BankDocument
    from app.services.tools import BankRepository

    queries = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    results = []
    with session_factory()() as db:
        names = {document.id: document.filename for document in db.scalars(select(BankDocument))}
        repository = BankRepository(db)
        for item in queries:
            found = search_bank_analytics(item["query"], item["as_of"], TOP_RESULTS, repository)
            top = [
                {
                    "file": names.get(hit["document_id"], hit["document_id"]),
                    "page": hit["page"],
                    "document_date": hit["document_date"],
                    "date_unknown": hit["date_unknown"],
                    "historical": hit["historical"],
                    "score": hit["score"],
                    "excerpt": hit["excerpt"],
                }
                for hit in found["items"]
            ]
            expected = item["expected"]
            hit_positions = [
                index + 1
                for index, hit in enumerate(top)
                if any(hit["file"] == want["file"] and hit["page"] == want["page"] for want in expected)
            ]
            passed = (not top) if not expected else bool(hit_positions)
            results.append(
                {
                    "id": item["id"],
                    "query": item["query"],
                    "as_of": item["as_of"],
                    "expected": expected,
                    "expected_note": item.get("note"),
                    "verified_by": item.get("verified_by"),
                    "result": "PASS" if passed else "FAIL",
                    "first_expected_rank": hit_positions[0] if hit_positions else None,
                    "returned": len(top),
                    "empty_reason": found["empty_reason"],
                    "top": top,
                }
            )
    report = {
        "checked_at": date.today().isoformat(),
        "top_k": TOP_RESULTS,
        "passed": sum(1 for item in results if item["result"] == "PASS"),
        "total": len(results),
        "queries": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("passed", "total")}, ensure_ascii=False))
    return 0 if report["passed"] == report["total"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.rag")
    commands = parser.add_subparsers(dest="command", required=True)
    reindex = commands.add_parser("reindex")
    reindex.add_argument("--pdf-dir")
    reindex.add_argument("--document-id")
    reindex.add_argument("--migrate", action="store_true")
    reindex.set_defaults(run=run_reindex)
    check = commands.add_parser("check")
    check.add_argument("--queries", default="../docs/ai/retrieval-queries.json")
    check.add_argument("--output", default="../docs/ai/retrieval-checks.json")
    check.set_defaults(run=run_check)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())

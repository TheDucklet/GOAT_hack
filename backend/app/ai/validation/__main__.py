import argparse
import json
import sys
from pathlib import Path

from app.ai.insights.context import company_facts
from app.ai.validation.catalog import Catalog
from app.ai.validation.checks import check_claim


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def catalog_from(spec: dict, companies: dict, chunks: dict) -> Catalog:
    context = companies[spec["company_id"]]
    features = {
        name: str(entry.get("value", ""))
        for name, entry in context["features"].items()
        if str(entry.get("value", "")).strip()
    }
    news = {
        item["id"]: {
            "id": item["id"],
            "kind": "news",
            "source_id": item["source_id"],
            "version": item["version"],
            "url": item["url"],
            "locator": {"url": item["url"]},
            "excerpt": item["excerpt"],
            "text": item["text"],
        }
        for item in spec["news"]
    }
    return Catalog(
        company_id=context["company_id"],
        profile_version=context["profile_version"],
        features=features,
        company_excerpts={fact.feature: fact.excerpt for fact in company_facts(context)},
        news=news,
        bank_hits=[chunks[chunk_id] for chunk_id in spec["bank_chunks"]],
        event_texts=[spec["event"]["title"], spec["event"]["summary"]],
        known_features=frozenset(features),
    )


def run_case(case: dict, catalog: Catalog) -> dict:
    evidence_by_id = {**catalog.news, **{item["id"]: item for item in case["evidence"]}}
    verdict, problems, valid_refs, statuses = check_claim(
        case["claim"], case["section"], evidence_by_id, catalog
    )
    codes = [problem.code for problem in problems]
    expected = case["expected"]
    matched = verdict == expected["verdict"] and all(code in codes for code in expected["codes"])
    return {
        "name": case["name"],
        "section": case["section"],
        "claim": case["claim"],
        "verdict": verdict,
        "codes": codes,
        "evidence_status": statuses,
        "kept_refs": valid_refs,
        "expected": expected,
        "matched": matched,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.validation")
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--fixtures", default="../docs/ai/fixtures")
    parser.add_argument("--output", default="../docs/ai/validation-report.json")
    args = parser.parse_args(argv)
    fixtures = Path(args.fixtures)
    spec = load(fixtures / "validation-cases.json")
    companies = {item["company_id"]: item for item in load(fixtures / "companies.json")}
    chunks = {item["chunk_id"]: item for item in load(fixtures / "bank-chunks.json")}
    catalog = catalog_from(spec, companies, chunks)
    results = [run_case(case, catalog) for case in spec["cases"]]
    summary = {
        "cases": len(results),
        "matched": sum(1 for item in results if item["matched"]),
        "supported": sum(1 for item in results if item["verdict"] == "supported"),
        "insufficient": sum(1 for item in results if item["verdict"] == "insufficient"),
        "contradiction": sum(1 for item in results if item["verdict"] == "contradiction"),
    }
    Path(args.output).write_text(
        json.dumps({"summary": summary, "cases": results}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for item in results:
        print(f"{'ok ' if item['matched'] else 'ERR'} {item['name']}: {item['verdict']} {item['codes']}")
    return 0 if summary["matched"] == summary["cases"] else 1


if __name__ == "__main__":
    sys.exit(main())

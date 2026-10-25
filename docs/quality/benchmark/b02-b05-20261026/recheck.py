"""Recheck all six immutable model results after deterministic publication repair.

No upstream generation is repeated; every result is reverified by gate-6 and
judge-3. This is explicitly a publication-stage replay, not a new full benchmark.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_review import HERE, LIMIT, ROOT, RunBudgetConfig, digest, git, read, write  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
SOURCE = ROOT / "artifacts/f16-b02-b05-20261026"
OUTPUT = ROOT / "artifacts/f16-b02-b05-recheck-20261026"
CAP = 3.41


def prepare():
    prior = read(SOURCE / "review-summary.json")
    if prior["budget"]["reserved_rub"] != 0 or prior["budget"]["spent_rub"] + CAP > LIMIT:
        raise SystemExit("Aggregate budget guard rejected replay")
    paths = [*sorted((SOURCE / "pairs").glob("*.json")), SOURCE / "events.json"]
    value = {
        "mode": "publication_stage_replay_of_six_immutable_generation_results",
        "generation_source_sha": prior["source_sha"],
        "prior_spent_rub": prior["budget"]["spent_rub"],
        "aggregate_limit_rub": LIMIT,
        "replay_limit_rub": CAP,
        "budget_day": prior["budget"]["day"],
        "files": {str(p.relative_to(SOURCE)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    write(HERE / "recheck-inputs.json", value)
    print(json.dumps({"files": len(paths), "sha256": digest(value)}))


def run():
    from app.ai.benchmark.judge import judge_card_v2
    from app.ai.benchmark.report_v2 import judge_v2, positive_cases
    from app.ai.budget import BudgetLedger
    from app.ai.gate.apply import enforce_publication
    from app.ai.gate.pipeline import news_texts
    from app.ai.providers import gateway
    from app.ai.providers.settings import LLMSettings
    from app.insight_provenance import validate_v2_provenance
    from app.schemas import AIEnvelope, InsightResultV2
    from app.services.publication import require_publication

    fixed = read(HERE / "recheck-inputs.json")
    if git("status", "--porcelain") or OUTPUT.exists():
        raise SystemExit("Clean committed tree and new replay directory required")
    for relative, expected in fixed["files"].items():
        if hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest() != expected:
            raise SystemExit("Saved input changed after freeze")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != fixed["runner_sha256"]:
        raise SystemExit("Replay runner changed")
    OUTPUT.mkdir(parents=True)
    settings = LLMSettings(
        _env_file=ROOT / ".env.ai", llm_daily_limit_rub=CAP,
        llm_budget_ledger_path=OUTPUT / "budget.jsonl", llm_usage_log_path=OUTPUT / "usage.jsonl",
        llm_max_retries=1, llm_timeout_seconds=60,
    )
    if settings.llm_base_url.rstrip("/") != "https://changellenge.up.railway.app/v1":
        raise SystemExit("Unapproved gateway")
    ledger = BudgetLedger(RunBudgetConfig(daily_limit_rub=CAP, anchored_day=date.fromisoformat(fixed["budget_day"])), settings.llm_budget_ledger_path)
    gateway.get_llm_settings = lambda: settings
    gateway.default_ledger = lambda _: ledger
    import app.ai.benchmark.judge as judge_module

    judge_module.get_llm_settings = lambda: settings
    events = {event["id"]: event for event in read(SOURCE / "events.json")}
    pairs = {}
    error = None
    write(OUTPUT / "run.json", {**fixed, "source_sha": git("rev-parse", "HEAD"), "started_at": datetime.now(UTC).isoformat()})
    try:
        for relative in fixed["files"]:
            if not relative.startswith("pairs/"):
                continue
            record = read(SOURCE / relative)
            envelope = enforce_publication(record["envelope"], news_texts(events[record["event_id"]]))
            parsed = AIEnvelope.model_validate(envelope)
            result = InsightResultV2.model_validate(parsed.result)
            validate_v2_provenance(result, parsed.evidence)
            require_publication(parsed, result.model_dump(mode="json"), "insight")
            record.update(envelope=envelope, status="ok", backend_publication="allow")
            pairs[record["pair_id"]] = record
            write(OUTPUT / relative, record)
            print(json.dumps({"stage": "recheck", "case": record["pair_id"], "mechanism": len(result.mechanism), "budget": ledger.status()}), flush=True)
        publications = {p["id"]: p["text"] for event in events.values() for p in event["publications"]}
        chunks = read(ROOT / "docs/ai/fixtures/bank-chunks.json")
        for key, record in pairs.items():
            context = {}
            for item in record["envelope"]["evidence"]:
                locator = item.get("locator") or {}
                texts = [c["text"] for c in chunks if c["filename"].startswith(locator.get("title") or "~") and c["page"] == locator.get("page")]
                if texts:
                    context[item["id"]] = " ".join(texts)
            write(OUTPUT / "judge2" / (key + ".json"), judge_card_v2(record["envelope"], publications, context))
            print(json.dumps({"stage": "judge", "case": key, "budget": ledger.status()}), flush=True)
    except Exception as exc:
        error = {"code": getattr(exc, "code", type(exc).__name__)}
    finally:
        required = read(HERE / "inputs.json")["pairs"]
        summary = {
            "mode": fixed["mode"], "source_sha": git("rev-parse", "HEAD"),
            "generation_source_sha": fixed["generation_source_sha"],
            "cases": positive_cases(pairs, required, None), "judge": judge_v2(OUTPUT, pairs),
            "budget": ledger.status(), "prior_spent_rub": fixed["prior_spent_rub"],
            "total_task_spent_rub": round(fixed["prior_spent_rub"] + ledger.status()["spent_rub"], 6),
            "error": error, "full_f16_acceptance": "INCOMPLETE: replay, no full final-SHA generation or independent calibration",
        }
        write(OUTPUT / "review-summary.json", summary)
        print(json.dumps(summary), flush=True)
        secret = settings.llm_api_key.get_secret_value().encode()
        if any(secret in p.read_bytes() for p in OUTPUT.rglob("*") if p.is_file()):
            raise SystemExit("Secret scan failed")
    return 0 if not error and summary["cases"]["passed"] == 6 else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        raise SystemExit(run())

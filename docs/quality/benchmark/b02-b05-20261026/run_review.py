"""Opt-in, budget-limited review of six existing F-16 regression cases."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
HERE = Path(__file__).resolve().parent
BASE = HERE.parent
OUTPUT = ROOT / "artifacts/f16-b02-b05-20261026"
GATEWAY = "https://changellenge.up.railway.app/v1"
LIMIT = 9.69

from app.ai.budget import BudgetConfig  # noqa: E402


class RunBudgetConfig(BudgetConfig):
    anchored_day: date

    def day_of(self, moment):
        return self.anchored_day


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def git(*args):
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT, text=True
    ).strip()


def prepare():
    from app.ai.benchmark.data import load_contexts
    from app.ai.budget import BudgetConfig

    if (HERE / "inputs.json").exists():
        raise SystemExit("Frozen inputs already exist; no overwrite permitted")
    required = read(BASE / "targets-ranking-v2.json")["positive_cases"]
    contexts = {item.context_id: item.context for item in load_contexts(BASE)}
    event_ids = {key.split("__", 1)[1] for key in required}
    events = [item for item in read(BASE / "events.json")["events"] if item["id"] in event_ids]
    focuses = read(BASE / "runs/run-3/focuses.json")
    chunks = ROOT / "docs/ai/fixtures/bank-chunks.json"
    value = {
        "approved_limit_rub": LIMIT,
        "prepared_at": datetime.now(UTC).isoformat(),
        "budget_day": BudgetConfig().day_of(datetime.now(UTC)).isoformat(),
        "baseline_main_sha": "9bc77e99d1da8d47c462763a84c9da6403e59532",
        "as_of": "2026-10-23T18:00:00+03:00",
        "pairs": required,
        "contexts": {key.split("__", 1)[0]: contexts[key.split("__", 1)[0]] for key in required},
        "events": events,
        "focuses": focuses,
        "focus_origin": "runs/run-3/focuses.json (frozen, no new model call)",
        "bank_chunks_sha256": hashlib.sha256(chunks.read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limitations": [
            "regression cases, not holdout",
            "CBR event is a frozen paraphrase; housing and IT are synthetic",
            "local file-repository tools, not PostgreSQL/VPS/API acceptance",
            "judge-3 is not independently human-calibrated",
        ],
    }
    value["inputs_sha256"] = digest(value)
    write(HERE / "inputs.json", value)
    print(json.dumps({"prepared": len(required), "events": len(events), "sha256": value["inputs_sha256"]}))


def run():
    import httpx

    from app.ai.benchmark.data import event_payload, load_contexts
    from app.ai.benchmark.judge import judge_card_v2
    from app.ai.benchmark.report_v2 import judge_v2, positive_cases
    from app.ai.benchmark.runner import metadata, run_pair
    from app.ai.budget import BudgetConfig, BudgetLedger
    from app.ai.insights.local_tools import repository_search
    from app.ai.providers import ALLOWED_MODEL_IDS, LLMError
    from app.ai.providers import gateway as gateway_module
    from app.ai.providers.settings import LLMSettings, get_llm_settings
    from app.ai.rag.file_repository import FileRepository
    from app.ai.summarization.summarize import summarize_event
    from app.insight_provenance import validate_v2_provenance
    from app.schemas import AIEnvelope, InsightResultV2
    from app.services.publication import require_publication

    frozen = read(HERE / "inputs.json")
    given_hash = frozen.pop("inputs_sha256")
    if digest(frozen) != given_hash:
        raise SystemExit("Input hash mismatch")
    frozen["inputs_sha256"] = given_hash
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != frozen["runner_sha256"]:
        raise SystemExit("Runner changed after freeze")
    if git("status", "--porcelain"):
        raise SystemExit("Commit the plan, inputs and runner first; clean tree required")
    if OUTPUT.exists():
        raise SystemExit("Run directory exists; no fresh budget or repeated outputs under this run ID")
    OUTPUT.mkdir(parents=True)
    chunks_path = ROOT / "docs/ai/fixtures/bank-chunks.json"
    if hashlib.sha256(chunks_path.read_bytes()).hexdigest() != frozen["bank_chunks_sha256"]:
        raise SystemExit("Bank corpus changed after freeze")
    settings = LLMSettings(
        _env_file=ROOT / ".env.ai",
        llm_daily_limit_rub=LIMIT,
        llm_budget_ledger_path=OUTPUT / "budget.jsonl",
        llm_usage_log_path=OUTPUT / "usage.jsonl",
        llm_max_retries=1,
        llm_retry_backoff_seconds=1.0,
        llm_timeout_seconds=60,
    )
    if settings.llm_base_url.rstrip("/") != GATEWAY:
        raise SystemExit("Gateway differs from approved host")
    if not settings.llm_api_key or not settings.llm_api_key.get_secret_value():
        raise SystemExit("Server key is not configured")
    if set(settings.llm_task_models.values()) - ALLOWED_MODEL_IDS:
        raise SystemExit("Configured task model outside allowlist")
    get_llm_settings.cache_clear()
    gateway_module.get_llm_settings = lambda: settings
    # All application call_llm aliases resolve the same function globals. Other
    # callers that inspect settings use this same explicit provider configuration.
    import app.ai.providers.settings as settings_module

    settings_module.get_llm_settings = lambda: settings
    import app.ai.benchmark.judge as judge_module
    import app.ai.benchmark.runner as runner_module

    runner_module.get_llm_settings = lambda: settings
    judge_module.get_llm_settings = lambda: settings

    config = RunBudgetConfig(
        **BudgetConfig.load(settings.llm_budget_limits_path).model_dump(),
        anchored_day=date.fromisoformat(frozen["budget_day"]),
    ).model_copy(update={"daily_limit_rub": LIMIT})
    ledger = BudgetLedger(config, settings.llm_budget_ledger_path)
    gateway_module.default_ledger = lambda _: ledger
    original_build = runner_module.build_published_insight
    runner_module.build_published_insight = lambda *args: original_build(
        *args, now=datetime.fromisoformat(frozen["as_of"])
    )
    started = time.monotonic()
    run_meta = metadata("frozen bank-chunks file repository")
    run_meta.update(
        source={"sha": git("rev-parse", "HEAD"), "tree_clean": True},
        approved_limit_rub=LIMIT,
        inputs_sha256=given_hash,
        as_of=frozen["as_of"],
        anchored_budget_day=frozen["budget_day"],
        concurrency=1,
        pair_retries=0,
        transport_retries=1,
    )
    write(OUTPUT / "run.json", run_meta)
    write(OUTPUT / "inputs.json", frozen)
    pairs = {}
    diagnostics = {}
    fatal = None
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(
                GATEWAY + "/models",
                headers={"Authorization": "Bearer " + settings.llm_api_key.get_secret_value()},
            )
        available = {
            item.get("id") for item in response.json().get("data", [])
        } if response.status_code == 200 else set()
        used = set(settings.llm_task_models.values())
        write(OUTPUT / "models.json", {"status": response.status_code, "configured_available": sorted(used & available)})
        if response.status_code != 200 or used - available:
            raise RuntimeError("Gateway model preflight failed; no generation started")
        events = {}
        for item in frozen["events"]:
            raw = event_payload(item)
            notes = {}
            summary = summarize_event(raw, notes)
            events[item["id"]] = {**raw, "summary": summary["summary"], "facts": summary["facts"], "topics": summary["topics"]}
            diagnostics[item["id"]] = notes
            write(OUTPUT / "events.json", list(events.values()))
            write(OUTPUT / "summary-diagnostics.json", diagnostics)
            print(json.dumps({"stage": "summary", "event_id": item["id"], "facts": len(summary["facts"]), "budget": ledger.status()}), flush=True)
        contexts = {context.context_id: context for context in load_contexts(BASE)}
        search = repository_search(FileRepository(chunks_path))
        for key in frozen["pairs"]:
            context_id, event_id = key.split("__", 1)
            context = contexts[context_id]
            if context.context != frozen["contexts"][context_id]:
                raise SystemExit("Synthetic context changed after freeze")
            record = run_pair(context, events[event_id], frozen["focuses"][context.role], search, retries=0)
            if record.get("envelope"):
                envelope = AIEnvelope.model_validate(record["envelope"])
                result = InsightResultV2.model_validate(envelope.result)
                validate_v2_provenance(result, envelope.evidence)
                try:
                    require_publication(envelope, result.model_dump(mode="json"), "insight")
                    record["backend_publication"] = "allow"
                except Exception as error:
                    record["backend_publication"] = getattr(error, "code", type(error).__name__)
                    if record["status"] == "ok":
                        record["status"] = "backend_rejected"
            pairs[key] = record
            write(OUTPUT / "pairs" / (key + ".json"), record)
            print(json.dumps({"stage": "pair", "pair_id": key, "status": record["status"], "budget": ledger.status()}), flush=True)
        publications = {p["id"]: p["text"] for event in events.values() for p in event["publications"]}
        chunks = read(chunks_path)
        for key, record in pairs.items():
            if record["status"] != "ok":
                continue
            time.sleep(2)
            context = {}
            for evidence in record["envelope"]["evidence"]:
                locator = evidence.get("locator") or {}
                title = locator.get("title") or "~"
                texts = [c["text"] for c in chunks if c["filename"].startswith(title) and c["page"] == locator.get("page")]
                if texts:
                    context[evidence["id"]] = " ".join(texts)
            try:
                judged = judge_card_v2(record["envelope"], publications, context)
                write(OUTPUT / "judge2" / (key + ".json"), judged)
                print(json.dumps({"stage": "judge", "pair_id": key, "claims": len(judged["claims"]), "budget": ledger.status()}), flush=True)
            except LLMError as error:
                write(OUTPUT / "judge-errors" / (key + ".json"), {"error": error.code, "request_id": error.request_id})
                if error.code == "budget_exhausted":
                    break
    except Exception as error:
        fatal = {"code": getattr(error, "code", type(error).__name__)}
        write(OUTPUT / "error.json", fatal)
    finally:
        report = {
            "source_sha": run_meta["source"]["sha"],
            "baseline_main_sha": frozen["baseline_main_sha"],
            "cases": positive_cases(pairs, frozen["pairs"], None),
            "judge": judge_v2(OUTPUT, pairs),
            "budget": ledger.status(),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "error": fatal,
            "full_f16_acceptance": "INCOMPLETE: six regression cases, no independent calibration or VPS/worker acceptance",
        }
        write(OUTPUT / "review-summary.json", report)
        print(json.dumps({"result": report["cases"], "budget": report["budget"], "error": fatal}), flush=True)
        # Never publish a file containing the configured server key.
        secret = settings.llm_api_key.get_secret_value().encode()
        leaks = [str(p.relative_to(OUTPUT)) for p in OUTPUT.rglob("*") if p.is_file() and secret in p.read_bytes()]
        if leaks:
            raise SystemExit("Secret scan failed; keep artifacts private")
    return 0 if not fatal and len(pairs) == 6 else 2


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

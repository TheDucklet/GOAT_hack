"""One fresh agent/generation smoke on the fixed code, sharing replay budget."""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_review import HERE, ROOT, RunBudgetConfig, git, read, write  # noqa: E402


def main():
    import app.ai.benchmark.judge as judge
    import app.ai.benchmark.runner as runner
    from app.ai.benchmark.data import load_contexts
    from app.ai.benchmark.judge import judge_card_v2
    from app.ai.benchmark.report_v2 import positive_cases
    from app.ai.budget import BudgetLedger
    from app.ai.insights.local_tools import repository_search
    from app.ai.providers import gateway
    from app.ai.providers.settings import LLMSettings
    from app.ai.rag.file_repository import FileRepository
    from app.schemas import AIEnvelope, InsightResultV2
    from app.services.publication import require_publication

    source = ROOT / "artifacts/f16-b02-b05-20261026"
    replay = ROOT / "artifacts/f16-b02-b05-recheck2-20261026"
    output = replay / "fresh-housing"
    if git("status", "--porcelain") or output.exists():
        raise SystemExit("Clean source and new smoke directory required")
    frozen = read(HERE / "inputs.json")
    key = "B02-finance_director__ev-syn-housing"
    settings = LLMSettings(
        _env_file=ROOT / ".env.ai", llm_daily_limit_rub=3.41,
        llm_budget_ledger_path=replay / "budget.jsonl", llm_usage_log_path=replay / "usage.jsonl",
        llm_max_retries=1, llm_timeout_seconds=60,
    )
    if settings.llm_base_url.rstrip("/") != "https://changellenge.up.railway.app/v1":
        raise SystemExit("Unapproved gateway")
    ledger = BudgetLedger(RunBudgetConfig(daily_limit_rub=3.41, anchored_day=read(HERE / "recheck-inputs.json")["budget_day"]), settings.llm_budget_ledger_path)
    before = ledger.status()
    if before["reserved_rub"] or before["remaining_rub"] < 1.0:
        raise SystemExit("Insufficient shared remaining budget")
    gateway.get_llm_settings = lambda: settings
    gateway.default_ledger = lambda _: ledger
    runner.get_llm_settings = lambda: settings
    judge.get_llm_settings = lambda: settings
    original = runner.build_published_insight
    runner.build_published_insight = lambda *args: original(*args, now=datetime.fromisoformat(frozen["as_of"]))
    write(output / "plan.json", {"source_sha": git("rev-parse", "HEAD"), "pair_id": key, "mode": "fresh_agent_and_generation_on_frozen_verified_summary", "budget_before": before})
    error = None
    record = None
    judged = None
    try:
        context = next(c for c in load_contexts(HERE.parent) if c.context_id == "B02-finance_director")
        event = next(e for e in read(source / "events.json") if e["id"] == "ev-syn-housing")
        search = repository_search(FileRepository(ROOT / "docs/ai/fixtures/bank-chunks.json"))
        record = runner.run_pair(context, event, frozen["focuses"][context.role], search, retries=0)
        write(output / "pair.json", record)
        envelope = AIEnvelope.model_validate(record["envelope"])
        result = InsightResultV2.model_validate(envelope.result)
        require_publication(envelope, result.model_dump(mode="json"), "insight")
        judged = judge_card_v2(record["envelope"], {p["id"]: p["text"] for p in event["publications"]}, {})
        write(output / "judge.json", judged)
    except Exception as exc:
        error = {"code": getattr(exc, "code", type(exc).__name__)}
    finally:
        summary = {
            "cases": positive_cases({key: record} if record else {}, [key], None),
            "error": error, "budget_after": ledger.status(),
            "task_spent_rub": round(read(source / "review-summary.json")["budget"]["spent_rub"] + ledger.status()["spent_rub"], 6),
            "judge": {"claims": len(judged["claims"]), "supported": sum(c["verdict"] == "supported" for c in judged["claims"])} if judged else None,
        }
        write(output / "summary.json", summary)
        write(replay / "budget-final.json", summary)
        print(json.dumps(summary), flush=True)
        secret = settings.llm_api_key.get_secret_value().encode()
        if any(secret in p.read_bytes() for p in output.rglob("*") if p.is_file()):
            raise SystemExit("Secret scan failed")
    return 0 if not error and summary["cases"]["passed"] == 1 else 2


if __name__ == "__main__":
    if sys.argv[1:] != ["--allow-paid"]:
        raise SystemExit("Explicit --allow-paid required")
    raise SystemExit(main())

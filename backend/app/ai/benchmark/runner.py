import json
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from app.ai.agent.prompts import AGENT_PROMPT_VERSION
from app.ai.benchmark.data import (
    DEFAULT_DIRECTORY,
    BenchmarkContext,
    event_payload,
    load_contexts,
    load_events,
    load_positions,
    pair_id,
)
from app.ai.benchmark.judge import JUDGE2_PROMPT_VERSION
from app.ai.gate.pipeline import build_published_insight
from app.ai.gate.prompts import GATE_PROMPT_VERSION
from app.ai.impact.prompts import IMPACT_PROMPT_VERSION
from app.ai.insights.local_tools import LocalTools, repository_search
from app.ai.insights.prompts import INSIGHT_PROMPT_VERSION
from app.ai.personalization.focus import FOCUS_PROMPT_VERSION, derive_user_focus
from app.ai.providers import LLMError, get_llm_settings
from app.ai.rag.file_repository import FileRepository
from app.ai.summarization.prompts import FACT_CHECK_PROMPT_VERSION, SUMMARY_PROMPT_VERSION
from app.ai.summarization.summarize import summarize_event
from app.ai.validation import VALIDATION_VERSION
from app.insight_versions import contract_versions
from app.publication_policy import PUBLICATION_POLICY_VERSION

DEFAULT_FIXTURES = Path("../docs/ai/fixtures")
AS_OF_NOW = datetime.fromisoformat("2026-10-23T18:00:00+03:00")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_sha() -> dict:
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout.strip()

    return {
        "sha": git("rev-parse", "HEAD") or "unknown",
        "tree_clean": not git("status", "--porcelain", "--", ".", "../docs/quality/benchmark"),
    }


def metadata(search_backend: str, extra: dict | None = None) -> dict:
    settings = get_llm_settings()
    return {
        **(extra or {}),
        "started_at": datetime.now(UTC).isoformat(),
        "source": source_sha(),
        "as_of_now": AS_OF_NOW.isoformat(),
        "search_backend": search_backend,
        "contract_versions": contract_versions(),
        "prompt_versions": {
            "summary": SUMMARY_PROMPT_VERSION,
            "focus": FOCUS_PROMPT_VERSION,
            "insight": INSIGHT_PROMPT_VERSION,
            "agent": AGENT_PROMPT_VERSION,
            "impact": IMPACT_PROMPT_VERSION,
            "validation": VALIDATION_VERSION,
            "gate": GATE_PROMPT_VERSION,
            "fact_check": FACT_CHECK_PROMPT_VERSION,
            "judge": JUDGE2_PROMPT_VERSION,
            "publication_policy": PUBLICATION_POLICY_VERSION,
        },
        "models": dict(sorted(settings.llm_task_models.items())),
    }


def summarized_events(run_dir: Path, directory: Path) -> list[dict]:
    path = run_dir / "events.json"
    if path.exists():
        return read(path)
    result, diagnostics = [], {}
    for item in load_events(directory):
        raw = event_payload(item)
        notes: dict = {}
        summary = summarize_event(raw, notes)
        diagnostics[item["id"]] = notes
        result.append(
            {**raw, "summary": summary["summary"], "facts": summary["facts"], "topics": summary["topics"]}
        )
    write(path, result)
    write(run_dir / "summary-diagnostics.json", diagnostics)
    return result


def focuses(run_dir: Path, directory: Path, contexts: list[BenchmarkContext]) -> dict[str, dict]:
    path = run_dir / "focuses.json"
    if path.exists():
        return read(path)
    positions = load_positions(directory)
    result = {}
    for role in sorted({context.role for context in contexts}):
        position = positions[role]
        result[role] = derive_user_focus(position["position_text"], position["interests"])
    write(path, result)
    return result


FATAL_CODES = {"budget_exhausted", "ai_unavailable", "model_not_allowed"}


def pair_cost(envelope: dict) -> tuple[float, int]:
    steps = [step for step in envelope["trace"]["steps"] if "llm" in step]
    report = envelope["trace"].get("publication") or {}
    return (
        round(sum(step.get("cost_rub", 0) for step in steps) + report.get("cost_rub", 0), 6),
        len(steps) + len(report.get("usage", [])),
    )


def run_pair(
    context: BenchmarkContext,
    event: dict,
    focus: dict,
    search: Callable,
    suppressed: int = 0,
    retries: int = 0,
) -> dict:
    calls: list[dict] = []

    def logged(query: str, as_of: str, limit: int) -> dict:
        hidden = len(calls) < suppressed
        found = (
            {
                "items": [],
                "query": query,
                "as_of": as_of,
                "empty_reason": "результат скрыт в целевой проверке",
            }
            if hidden
            else search(query, as_of, limit)
        )
        calls.append(
            {
                "query": query,
                "as_of": as_of,
                "limit": limit,
                "suppressed": hidden,
                "chunk_ids": [item["chunk_id"] for item in found.get("items", [])],
            }
        )
        return found

    started = time.monotonic()
    record = {
        "pair_id": pair_id(context.context_id, event["id"]),
        "context_id": context.context_id,
        "event_id": event["id"],
    }
    failures: list[dict] = []
    for attempt in range(retries + 1):
        try:
            envelope = build_published_insight(
                context.context, focus, event, LocalTools(context.context, event, logged)
            )
        except LLMError as error:
            if error.code in FATAL_CODES:
                raise
            failures.append({"attempt": attempt + 1, "error": error.code})
            continue
        cost, calls_made = pair_cost(envelope)
        allowed = envelope["trace"].get("publication", {}).get("decision") == "allow"
        return {
            **record,
            "status": "ok" if allowed else "blocked",
            "latency_seconds": round(time.monotonic() - started, 2),
            "cost_rub": cost,
            "llm_calls": calls_made,
            "failed_attempts": failures,
            "searches": calls,
            "envelope": envelope,
        }
    return {
        **record,
        "status": "error",
        "error": failures[-1]["error"],
        "failed_attempts": failures,
        "latency_seconds": round(time.monotonic() - started, 2),
        "searches": calls,
    }


def run_all(
    run_dir: Path,
    directory: Path = DEFAULT_DIRECTORY,
    fixtures: Path = DEFAULT_FIXTURES,
    workers: int = 3,
    only: set[str] | None = None,
    events_dir: Path | None = None,
    limit_rub: float | None = None,
    retries: int = 0,
    extra_meta: dict | None = None,
) -> dict:
    contexts = [c for c in load_contexts(directory) if not only or c.context_id in only]
    events = summarized_events(run_dir, events_dir or directory)
    role_focus = focuses(run_dir, directory, contexts)
    search = repository_search(FileRepository(fixtures / "bank-chunks.json"))
    meta = {"limit_rub": limit_rub, "workers": workers, "retries": retries, **(extra_meta or {})}
    write(run_dir / "run.json", metadata("offline_snapshot: docs/ai/fixtures/bank-chunks.json", meta))
    jobs = [(context, event) for context in contexts for event in events]
    spent = {"rub": 0.0}
    lock = threading.Lock()

    def work(job):
        context, event = job
        path = run_dir / "pairs" / f"{pair_id(context.context_id, event['id'])}.json"
        if path.exists():
            return read(path)
        with lock:
            if limit_rub is not None and spent["rub"] >= limit_rub:
                return {"status": "not_started_budget", "pair_id": pair_id(context.context_id, event["id"])}
        record = run_pair(context, event, role_focus[context.role], search, retries=retries)
        with lock:
            spent["rub"] += record.get("cost_rub", 0.0)
        write(path, record)
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        records = list(pool.map(work, jobs))
    return {
        "pairs": len(records),
        "ok": sum(1 for item in records if item["status"] == "ok"),
        "blocked": sum(1 for item in records if item["status"] == "blocked"),
        "errors": sum(1 for item in records if item["status"] == "error"),
        "not_started": sum(1 for item in records if item["status"] == "not_started_budget"),
        "spent_rub": round(spent["rub"], 4),
    }

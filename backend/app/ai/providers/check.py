import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.ai.providers.gateway import LLMError, call_llm
from app.ai.providers.models import LLMInput, UsageRecord
from app.ai.providers.settings import get_llm_settings
from app.ai.providers.testing import ScriptedTransport, completion
from app.ai.providers.transport import TransportFailure
from app.ai.providers.usage import MemoryUsageSink

CHECK_TASK = "derive_user_focus"
CHECK_PROMPT = LLMInput(
    system="Верни только JSON-объект без пояснений.",
    user='Верни JSON {"status": "ok"}.',
)


def summarize(record: UsageRecord) -> dict:
    return {
        "request_id": record.request_id,
        "task": record.task,
        "model_id": record.model_id,
        "status": record.status,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "latency_ms": record.latency_ms,
        "cost_rub": record.cost_rub,
        "attempts": record.attempts,
    }


def controlled_failure(transport: ScriptedTransport) -> dict:
    settings = get_llm_settings().model_copy(update={"llm_retry_backoff_seconds": 0})
    sink = MemoryUsageSink()
    try:
        call_llm(
            CHECK_TASK,
            CHECK_PROMPT,
            50,
            settings=settings,
            transport=transport,
            usage_sink=sink,
            sleep=lambda seconds: None,
        )
    except LLMError as error:
        return {"error_code": error.code, "retryable": error.retryable, **summarize(sink.records[0])}
    raise RuntimeError("the controlled scenario unexpectedly succeeded")


def real_call() -> dict:
    sink = MemoryUsageSink()
    result = call_llm(CHECK_TASK, CHECK_PROMPT, 50, usage_sink=sink)
    return {"response_keys": sorted(result.data), **summarize(result.usage)}


def run(output: Path, offline: bool) -> dict:
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tariffs_basis": json.loads(get_llm_settings().llm_tariffs_path.read_text(encoding="utf-8"))["basis"],
        "real_call": None if offline else real_call(),
        "controlled_timeout": controlled_failure(
            ScriptedTransport(
                TransportFailure("timeout"), TransportFailure("timeout"), TransportFailure("timeout")
            )
        ),
        "controlled_invalid_json": controlled_failure(ScriptedTransport(completion("не JSON", 40, 5))),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.providers.check")
    parser.add_argument("--output", type=Path, default=Path("../docs/ai/provider-check.json"))
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run(args.output, args.offline)
    except LLMError as error:
        print(f"Проверка не пройдена: {error.code} – {error.message}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

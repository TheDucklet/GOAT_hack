import argparse
import json
import sys
from pathlib import Path

from app.ai.providers import LLMError
from app.ai.summarization.summarize import summarize_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.summarization")
    parser.add_argument("--events", default="../docs/ai/fixtures/events.json")
    parser.add_argument("--output", default="../docs/ai/summary-checks.json")
    args = parser.parse_args(argv)
    cases = json.loads(Path(args.events).read_text(encoding="utf-8"))
    results = []
    try:
        for case in cases:
            results.append(
                {
                    "name": case["name"],
                    "note": case["note"],
                    "input": case["event"],
                    "result": summarize_event(case["event"]),
                }
            )
    except LLMError as error:
        print(f"Проверка остановлена: {error.code} – {error.message}", file=sys.stderr)
        return 1
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"обработано событий: {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

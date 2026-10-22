import argparse
import json
import sys
from pathlib import Path

from app.ai.evaluation.pipeline import DEFAULT_FIXTURES, DEFAULT_INPUTS, Workspace, focus_of, summarized
from app.ai.impact.generate import build_impact_insight
from app.ai.insights.local_tools import LocalTools
from app.ai.providers import LLMError

CONTEXTS = Path("../docs/contracts/company-context-v2-examples.json")
CASES = [
    {"name": "credit_company_accountant", "company": "u-client", "position": "chief_accountant"},
    {"name": "no_credit_company_accountant", "company": "u-prospect", "position": "chief_accountant"},
    {"name": "credit_company_marketing_director", "company": "u-client", "position": "marketing_director"},
    {"name": "unconfirmed_profile_accountant", "company": "u-mixed", "position": "chief_accountant"},
]
EVENT = "inflation_weekly"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.impact")
    parser.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    parser.add_argument("--inputs", default=str(DEFAULT_INPUTS))
    parser.add_argument("--contexts", default=str(CONTEXTS))
    parser.add_argument("--output", default="../docs/ai/impact-examples.json")
    args = parser.parse_args(argv)
    workspace = Workspace(Path(args.fixtures), Path(args.inputs))
    contexts = {
        item["name"]: item["data"] for item in json.loads(Path(args.contexts).read_text(encoding="utf-8"))
    }
    results = []
    try:
        event, summary = summarized(workspace.raw_event(EVENT))
        focuses = {}
        for case in CASES:
            if case["position"] not in focuses:
                focuses[case["position"]] = focus_of(workspace.position(case["position"]))
            context = contexts[case["company"]]
            tools = LocalTools(context, event, workspace.search)
            envelope = build_impact_insight(context, focuses[case["position"]], event, tools)
            results.append({**case, "event": EVENT, "focus": focuses[case["position"]], "envelope": envelope})
            print(f"{case['name']}: {envelope['result']['impact_level']}")
    except LLMError as error:
        print(f"Проверка остановлена: {error.code} – {error.message}", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event, "summary": summary, "cases": results}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

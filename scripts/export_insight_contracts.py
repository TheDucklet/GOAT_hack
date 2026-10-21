"""Export F-13 artifacts from canonical Python models; run with PYTHONPATH=backend."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.ai.schemas import InsightEnvelopeV2
from app.notice_policy import notice_policy
from app.schemas import InsightResult, InsightResultV2

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    return {
        "insight.schema.json": TypeAdapter(
            InsightResultV2 | InsightResult
        ).json_schema(),
        "insight-envelope-v2.schema.json": InsightEnvelopeV2.model_json_schema(),
        "notice-policy.json": notice_policy(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, value in artifacts().items():
        path = ROOT / "docs/contracts" / name
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"Outdated generated contract: {path}")
        else:
            path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()

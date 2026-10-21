"""Export CompanyContext v2 JSON Schema from its canonical wire model."""

import argparse
import json
from pathlib import Path

from app.schemas import CompanyContextV2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "docs/contracts/company-context-v2.schema.json"
    content = json.dumps(CompanyContextV2.model_json_schema(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if path.read_text(encoding="utf-8") != content:
            raise SystemExit(f"Outdated contract: {path}")
    else:
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()

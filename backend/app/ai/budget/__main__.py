import argparse
import json
from pathlib import Path

from app.ai.budget.config import DEFAULT_LIMITS_PATH, BudgetConfig
from app.ai.budget.ledger import BudgetLedger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ai.budget")
    parser.add_argument("command", choices=["status"])
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--limits", type=Path, default=DEFAULT_LIMITS_PATH)
    args = parser.parse_args(argv)
    ledger = BudgetLedger(BudgetConfig.load(args.limits), args.ledger)
    print(json.dumps(ledger.status(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

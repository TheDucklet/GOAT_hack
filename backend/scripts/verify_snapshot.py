"""Independent reconciliation against CSV, intended for the real imported snapshot."""

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.db import session_factory
from app.models import Payment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    total, count, rows = Decimal(0), 0, 0
    controls = {}
    with (args.directory / "df_Uid_payment_hack.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            amount, quantity = Decimal(row["PAY_AMT"]), int(row["PAY_CNT"])
            total += amount
            count += quantity
            rows += 1
            payer = row["PAYER"]
            if payer not in controls and len(controls) < 3:
                controls[payer] = [Decimal(0), 0, 0]
            if payer in controls:
                controls[payer][0] += amount
                controls[payer][1] += quantity
                controls[payer][2] += 1
    with session_factory()() as db:
        actual_rows, actual_amount, actual_count = db.execute(
            select(
                func.count(),
                func.sum(Payment.amount),
                func.sum(Payment.payment_count),
            )
        ).one()
        assert (actual_rows, actual_amount, actual_count) == (rows, total, count)
        for payer, expected in controls.items():
            actual = db.execute(
                select(func.sum(Payment.amount), func.sum(Payment.payment_count), func.count()).where(
                    Payment.payer == payer
                )
            ).one()
            assert tuple(expected) == tuple(actual), payer
    report = {
        "passed": True,
        "rows": rows,
        "amount": str(total),
        "payment_count": count,
        "control_payers": [
            {"id": payer, "amount": str(values[0]), "payment_count": values[1], "rows": values[2]}
            for payer, values in controls.items()
        ],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

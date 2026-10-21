"""Reconcile source CSV against A-14 storage in an explicitly isolated audit database."""

import argparse
import csv
import json
import time
from decimal import Decimal
from itertools import zip_longest
from pathlib import Path

from app.ai.insights.context import company_facts
from app.cli import migrate
from app.data_semantics import (
    COMPANIES_FILE,
    DATA_SEMANTICS_VERSION,
    PAYMENTS_FILE,
    PEOPLE_FILE,
)
from app.db import get_engine, session_factory
from app.models import ClientRawRow, Company, Membership, Payment
from app.schemas import CompanyContextV2
from app.services.clients import company_context, demo_candidates, import_clients
from sqlalchemy import func, select


def verify(directory: Path) -> dict:
    engine = get_engine()
    if engine.dialect.name != "postgresql" or engine.url.database != "goat_a14":
        raise SystemExit(
            "Full reconciliation requires the isolated PostgreSQL database named goat_a14"
        )
    migrate()
    started = time.perf_counter()
    with session_factory()() as db, db.begin():
        memberships = db.scalar(select(func.count()).select_from(Membership))
        report = import_clients(db, directory)
    imported_at = time.perf_counter()
    print(
        f"Imported {report['company_rows']} company rows and {report['payment_rows']} payment rows",
        flush=True,
    )
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    with session_factory()() as db, db.begin():
        for file in [COMPANIES_FILE, PEOPLE_FILE]:
            with (directory / file).open(encoding="utf-8-sig", newline="") as stream:
                source = list(csv.DictReader(stream, delimiter=";"))
            stored = list(
                db.scalars(
                    select(ClientRawRow)
                    .where(
                        ClientRawRow.batch_id == report["version"],
                        ClientRawRow.file == file,
                    )
                    .order_by(ClientRawRow.row_number)
                )
            )
            check(f"exact_raw_rows:{file}", [item.raw for item in stored] == source)
        partition = dict(
            db.execute(
                select(ClientRawRow.status, func.count())
                .where(
                    ClientRawRow.batch_id == report["version"],
                    ClientRawRow.file == COMPANIES_FILE,
                )
                .group_by(ClientRawRow.status)
            ).all()
        )
        check(
            "company_rows_partition",
            partition.get("normalized", 0) == report["normalized_company_rows"]
            and partition.get("quarantine", 0) == report["quarantined_company_rows"],
        )
        observed = {}
        for classification, amount, count, rows in db.execute(
            select(
                Payment.classification,
                func.sum(Payment.amount),
                func.sum(Payment.payment_count),
                func.count(),
            ).group_by(Payment.classification)
        ):
            observed[classification] = {
                "amount": str(amount),
                "payment_count": int(count),
                "row_count": rows,
            }
        for kind, expected in report["payment_classification"].items():
            actual = observed.get(
                kind, {"amount": "0", "payment_count": 0, "row_count": 0}
            )
            check(
                f"stored_payment_totals:{kind}",
                Decimal(actual["amount"]) == Decimal(expected["amount"])
                and actual["payment_count"] == expected["payment_count"]
                and actual["row_count"] == expected["row_count"],
            )
        amount, count, raw_rows = Decimal(0), 0, 0
        with (directory / PAYMENTS_FILE).open(
            encoding="utf-8-sig", newline=""
        ) as stream:
            source = csv.DictReader(stream, delimiter=";")
            stored = db.execute(
                select(
                    Payment.raw,
                    Payment.amount,
                    Payment.payment_count,
                    Payment.row_number,
                    Payment.payer,
                    Payment.beneficiary,
                ).order_by(Payment.row_number)
            ).yield_per(2000)
            for expected, actual in zip_longest(source, stored):
                if expected is None or actual is None:
                    raise AssertionError("payment raw row count mismatch")
                raw, normalized_amount, normalized_count, number, payer, beneficiary = (
                    actual
                )
                if (
                    raw != expected
                    or number != raw_rows + 2
                    or normalized_amount != Decimal(expected["PAY_AMT"])
                    or normalized_count != Decimal(expected["PAY_CNT"])
                    or payer != expected["PAYER"].strip()
                    or beneficiary != expected["BENEFICIARY"].strip()
                ):
                    raise AssertionError(
                        f"payment source/normalized mismatch at row {number}"
                    )
                raw_rows += 1
                amount += normalized_amount
                count += normalized_count
        check(
            "every_payment_raw_and_normalized_row",
            raw_rows == report["payment_rows"]
            and amount == Decimal(report["payment_amount"])
            and count == report["payment_count"],
        )
        check(
            "membership_unchanged",
            memberships == db.scalar(select(func.count()).select_from(Membership)),
        )
        samples = []
        for client_type in ["Client", "Prospect", "Closed Client"]:
            key = db.scalar(
                select(Company.id)
                .where(
                    Company.client_type == client_type,
                    Company.identity_quality == "confirmed",
                )
                .order_by(Company.id)
                .limit(1)
            )
            if key:
                context = company_context(db, key)
                CompanyContextV2.model_validate(context)
                check(
                    f"safe_context:{client_type}",
                    "REVENUE_COMPANY"
                    not in {fact.feature for fact in company_facts(context)}
                    and context["payment_summary"]["period"] is None,
                )
                samples.append(
                    {
                        "client_type": client_type,
                        "schema_version": context["schema_version"],
                        "identity_quality": context["identity_quality"],
                    }
                )
        for key in report["quarantined_company_ids"]:
            context = company_context(db, key)
            check(
                "quarantined_context_has_no_company_facts",
                company_facts(context) == [] and not context["relationships"],
            )
        candidates = demo_candidates(db, 100)
        check(
            "demo_clients_only",
            bool(candidates)
            and all(
                company.client_type == "Client"
                and company.identity_quality == "confirmed"
                for company in candidates
            ),
        )
        check(
            "idempotent_same_semantics_and_files",
            import_clients(db, directory)["already_imported"] is True,
        )
    total = Decimal(report["payment_amount"])
    self_amount = Decimal(report["payment_classification"]["self"]["amount"])
    report["measured_self_payment_share"] = {
        "amount": str(self_amount / total) if total else None,
        "count": str(
            Decimal(report["payment_classification"]["self"]["payment_count"])
            / report["payment_count"]
        )
        if report["payment_count"]
        else None,
        "rows": str(
            Decimal(report["payment_classification"]["self"]["row_count"])
            / report["payment_rows"]
        )
        if report["payment_rows"]
        else None,
    }
    report["verification"] = {
        "result": "PASS",
        "database": "PostgreSQL",
        "semantics": DATA_SEMANTICS_VERSION,
        "checks": checks,
        "sample_contexts": samples,
        "import_seconds": round(imported_at - started, 2),
        "verification_seconds": round(time.perf_counter() - imported_at, 2),
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report["verification"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

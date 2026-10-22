"""Full A18 coverage, independent historical totals and host memory measurement."""

import argparse
import json
import os
import platform
import sys
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text

from app.db import session_factory
from app.models import ClientRawRow, Company, Payment, PersonLink
from verify_data_semantics import verify


def peak_memory_bytes():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                )
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE
        measure = ctypes.windll.psapi.GetProcessMemoryInfo
        measure.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        measure.restype = wintypes.BOOL
        if not measure(current(), ctypes.byref(counters), counters.cb):
            raise OSError("cannot measure process memory")
        return counters.PeakWorkingSetSize
    import resource

    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = verify(args.directory)
    historical = json.loads((root / "docs/qa/real-snapshot.json").read_text())
    assert report["payment_rows"] == historical["rows"]
    assert Decimal(report["payment_amount"]) == Decimal(historical["amount"])
    assert report["payment_count"] == historical["payment_count"]
    classified = report["payment_classification"]
    for field in ("amount", "payment_count", "row_count"):
        expected = report[
            {"amount": "payment_amount", "payment_count": "payment_count", "row_count": "payment_rows"}[field]
        ]
        assert sum(Decimal(str(item[field])) for item in classified.values()) == Decimal(str(expected))
    with session_factory()() as db:
        groups = db.execute(
            select(func.count(func.distinct(Company.group_id)), func.count()).where(
                Company.group_id.is_not(None)
            )
        ).one()
        report["group_coverage"] = {
            "observed_groups": groups[0],
            "members_with_confirmed_group": groups[1],
            "consolidated_revenue": None,
            "reason": "units and periods unconfirmed",
        }
        report["person_row_accounting"] = dict(
            db.execute(
                select(ClientRawRow.status, func.count())
                .where(
                    ClientRawRow.file == "df_Fid_Uid_link_hack.csv",
                    ClientRawRow.batch_id == report["version"],
                )
                .group_by(ClientRawRow.status)
            ).all()
        )
        report["person_row_accounting"]["distinct_normalized_links"] = db.scalar(
            select(func.count()).select_from(PersonLink)
        )
        report["stored_payments"] = db.scalar(select(func.count()).select_from(Payment))
        report["database_bytes"] = db.scalar(text("SELECT pg_database_size(current_database())"))
    # Published proof is aggregate only. The isolated audit DB retains exact raw provenance.
    report["quarantined_company_id_count"] = len(report.pop("quarantined_company_ids"))
    report["conflicting_field_count"] = len(report.pop("conflicts"))
    report["historical_totals_match"] = True
    report["host"] = {
        "os": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "peak_process_working_set_bytes": peak_memory_bytes(),
        "memory_method": "OS process peak working set including import and full row verification",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "result": "PASS",
                "payment_rows": report["payment_rows"],
                "import_seconds": report["verification"]["import_seconds"],
                "peak_bytes": report["host"]["peak_process_working_set_bytes"],
            }
        )
    )


if __name__ == "__main__":
    main()

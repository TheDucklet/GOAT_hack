"""Atomic, source-preserving CSV import. Meaning lives in app.data_semantics."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, insert, select, text, update

from app.data_semantics import (
    COMPANIES_FILE,
    DATA_SEMANTICS_VERSION,
    PAYMENTS_FILE,
    PEOPLE_FILE,
    ambiguous_identity,
    clean,
    normalize_feature,
    suspicious_id,
)
from app.models import ClientRawRow, Company, ImportBatch, Payment, PersonLink

CHUNK_SIZE = 1000


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows(path: Path, required: set[str]):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not required.issubset(reader.fieldnames or []) or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError(f"Invalid headers in {path.name}: {sorted(required)}")
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed row {number} in {path.name}")
            yield number, row  # Exact source strings, including whitespace and numeric spelling.


def ident(value: str, number: int) -> str:
    value = clean(value)
    if value is None or len(value) > 100:
        raise ValueError(f"Invalid identifier at row {number}")
    return value


def parse_payment(row, number):
    try:
        amount, count = Decimal(row["PAY_AMT"].strip()), Decimal(row["PAY_CNT"].strip())
        if (
            not amount.is_finite()
            or not count.is_finite()
            or amount < 0
            or count <= 0
            or count != count.to_integral_value()
            or amount != amount.quantize(Decimal("0.01"))
            or amount >= Decimal("1e28")
            or count > 2147483647
        ):
            raise ValueError()
        return amount, int(count)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"Invalid payment at row {number}") from exc


def bulk(db, model, records):
    if records:
        db.execute(insert(model), records)
        records.clear()


def payment_classification(payer, beneficiary, ambiguous):
    if payer in ambiguous or beneficiary in ambiguous or suspicious_id(payer) or suspicious_id(beneficiary):
        return "quarantined"
    return "self" if payer == beneficiary else "external"


def import_clients(db, directory: Path) -> dict:
    """Caller owns the transaction; validation or changed inputs roll everything back."""
    hashes = {name: file_hash(directory / name) for name in [COMPANIES_FILE, PEOPLE_FILE, PAYMENTS_FILE]}
    version = hashlib.sha256(
        json.dumps({"files": hashes, "semantics": DATA_SEMANTICS_VERSION}, sort_keys=True).encode()
    ).hexdigest()
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(761202601)"))
    previous = db.get(ImportBatch, version)
    if previous and previous.active:
        return {**previous.report, "already_imported": True}
    grouped = defaultdict(list)
    for number, row in rows(directory / COMPANIES_FILE, {"SYNTHETIC_U", "GROUP_ID"}):
        grouped[ident(row["SYNTHETIC_U"], number)].append((number, row))
    ambiguous = {key for key, variants in grouped.items() if ambiguous_identity(key, variants)}
    all_ids = set(grouped)
    totals = {
        key: {"amount": Decimal(0), "payment_count": 0, "row_count": 0}
        for key in ["external", "self", "quarantined"]
    }
    for number, row in rows(directory / PAYMENTS_FILE, {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}):
        payer, beneficiary = ident(row["PAYER"], number), ident(row["BENEFICIARY"], number)
        all_ids.update([payer, beneficiary])
        amount, count = parse_payment(row, number)
        total = totals[payment_classification(payer, beneficiary, ambiguous)]
        total["amount"] += amount
        total["payment_count"] += count
        total["row_count"] += 1
    people = list(rows(directory / PEOPLE_FILE, {"SYNTHETIC_F", "SYNTHETIC_U", "CITY_NAME", "RC_NAME"}))
    all_ids.update(ident(row["SYNTHETIC_U"], number) for number, row in people)
    for number, row in people:
        ident(row["SYNTHETIC_F"], number)

    report = {
        "version": version,
        "data_semantics_version": DATA_SEMANTICS_VERSION,
        "files": hashes,
        "company_rows": sum(map(len, grouped.values())),
        "unique_companies": len(grouped),
        "quarantined_company_ids": sorted(ambiguous),
        "quarantined_company_rows": sum(len(grouped[key]) for key in ambiguous),
        "normalized_company_rows": sum(
            len(variants) for key, variants in grouped.items() if key not in ambiguous
        ),
        "conflicts": [],
        "missing_fields": {},
        "client_types": {},
        "person_links": 0,
        "person_rows": len(people),
        "quarantined_person_rows": 0,
        "payment_rows": sum(item["row_count"] for item in totals.values()),
        "payment_amount": str(sum((item["amount"] for item in totals.values()), Decimal(0))),
        "payment_count": sum(item["payment_count"] for item in totals.values()),
        "payment_classification": {
            key: {**value, "amount": str(value["amount"])} for key, value in totals.items()
        },
        "payment_unit": None,
        "payment_period": None,
        "placeholder_companies": len(all_ids - grouped.keys()),
        "already_imported": False,
    }
    # Keep historic raw snapshots and reports; only one normalized snapshot is active.
    db.execute(delete(Payment))
    db.execute(delete(PersonLink))
    db.execute(update(ImportBatch).values(active=False))
    if previous:
        previous.active, previous.report = True, json.loads(json.dumps(report))
        db.execute(delete(ClientRawRow).where(ClientRawRow.batch_id == version))
    else:
        db.add(ImportBatch(id=version, active=True, report=json.loads(json.dumps(report))))
    db.flush()
    db.execute(
        update(Company)
        .where(~Company.profile_version.like("demo-%"))
        .values(
            features={},
            unknowns=["profile_missing"],
            is_placeholder=True,
            group_id=None,
            profile_version=version,
            data_semantics_version=DATA_SEMANTICS_VERSION,
            identity_quality="placeholder",
            client_type=None,
        )
    )
    existing = set(db.scalars(select(Company.id)))
    additions, changes, raw_rows = [], [], []
    missing, client_types = Counter(), Counter()
    for key, variants in grouped.items():
        features = {
            field: normalize_feature(field, variants, hashes[COMPANIES_FILE], key in ambiguous)
            for field in variants[0][1]
            if field != "SYNTHETIC_U"
        }
        unknowns = [field for field, feature in features.items() if feature["value"] is None]
        missing.update(unknowns)
        for field, feature in features.items():
            if feature["quality"] == "conflicting":
                report["conflicts"].append(
                    {"company_id": key, "field": field, "rows": [n for n, _ in variants]}
                )
        client_type = features.get("CL_TYPE", {}).get("value")
        client_types[client_type or "unknown"] += 1
        company = dict(
            id=key,
            name=key,
            group_id=features["GROUP_ID"]["value"],
            features=features,
            unknowns=unknowns + (["identity_ambiguous"] if key in ambiguous else []),
            profile_version=version,
            data_semantics_version=DATA_SEMANTICS_VERSION,
            identity_quality="ambiguous" if key in ambiguous else "confirmed",
            client_type=client_type,
            is_placeholder=False,
        )
        (changes if key in existing else additions).append(company)
        for number, row in variants:
            raw_rows.append(
                dict(
                    batch_id=version,
                    file=COMPANIES_FILE,
                    row_number=number,
                    entity_id=key,
                    raw=row,
                    status="quarantine" if key in ambiguous else "normalized",
                    reason="ambiguous_company_identity" if key in ambiguous else None,
                )
            )
        if len(additions) >= CHUNK_SIZE:
            bulk(db, Company, additions)
        if len(changes) >= CHUNK_SIZE:
            db.execute(update(Company), changes)
            changes.clear()
        if len(raw_rows) >= CHUNK_SIZE:
            bulk(db, ClientRawRow, raw_rows)
    bulk(db, Company, additions)
    if changes:
        db.execute(update(Company), changes)
    bulk(db, ClientRawRow, raw_rows)
    placeholders = []
    for key in sorted(all_ids - grouped.keys() - existing):
        placeholders.append(
            dict(
                id=key,
                name=key,
                features={},
                unknowns=["profile_missing"],
                is_placeholder=True,
                profile_version=version,
                data_semantics_version=DATA_SEMANTICS_VERSION,
                identity_quality="ambiguous" if suspicious_id(key) else "placeholder",
            )
        )
        if len(placeholders) >= CHUNK_SIZE:
            bulk(db, Company, placeholders)
    bulk(db, Company, placeholders)
    report["missing_fields"], report["client_types"] = dict(missing), dict(client_types)

    links = {}
    for number, row in people:
        company_id, person_id = ident(row["SYNTHETIC_U"], number), ident(row["SYNTHETIC_F"], number)
        quarantined = company_id in ambiguous or suspicious_id(company_id) or suspicious_id(person_id)
        report["quarantined_person_rows"] += int(quarantined)
        raw_rows.append(
            dict(
                batch_id=version,
                file=PEOPLE_FILE,
                row_number=number,
                entity_id=company_id,
                raw=row,
                status="quarantine" if quarantined else "normalized",
                reason="ambiguous_link_identity" if quarantined else None,
            )
        )
        if not quarantined:
            key = (person_id, company_id, row["CITY_NAME"].strip(), row["RC_NAME"].strip())
            if key not in links:
                links[key] = dict(
                    person_id=person_id,
                    company_id=company_id,
                    city=key[2],
                    region=key[3],
                    provenance={
                        "file": PEOPLE_FILE,
                        "file_sha256": hashes[PEOPLE_FILE],
                        "rows": [],
                        "batch_id": version,
                    },
                )
            links[key]["provenance"]["rows"].append(number)
    for start in range(0, len(raw_rows), CHUNK_SIZE):
        db.execute(insert(ClientRawRow), raw_rows[start : start + CHUNK_SIZE])
    link_values = list(links.values())
    for start in range(0, len(link_values), CHUNK_SIZE):
        db.execute(insert(PersonLink), link_values[start : start + CHUNK_SIZE])
    report["person_links"] = len(links)

    def payments():
        for number, row in rows(directory / PAYMENTS_FILE, {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}):
            amount, count = parse_payment(row, number)
            payer, beneficiary = ident(row["PAYER"], number), ident(row["BENEFICIARY"], number)
            yield dict(
                batch_id=version,
                row_number=number,
                payer=payer,
                beneficiary=beneficiary,
                amount=amount,
                payment_count=count,
                raw=row,
                classification=payment_classification(payer, beneficiary, ambiguous),
            )

    write_payments(db, payments())
    if any(file_hash(directory / name) != sha for name, sha in hashes.items()):
        raise ValueError("Input files changed during import; transaction rolled back")
    # Assign a fresh JSON object: mutations of a plain JSON column are not tracked.
    db.get(ImportBatch, version).report = json.loads(json.dumps(report))
    db.flush()
    return report


def write_payments(db, payments):
    if db.bind.dialect.name == "postgresql":
        from psycopg.types.json import Jsonb

        driver = db.connection().connection.driver_connection
        with (
            driver.cursor() as cursor,
            cursor.copy(
                "COPY payments (batch_id,row_number,payer,beneficiary,amount,payment_count,raw,classification) FROM STDIN"
            ) as copy,
        ):
            for row in payments:
                copy.write_row(
                    (
                        row["batch_id"],
                        row["row_number"],
                        row["payer"],
                        row["beneficiary"],
                        row["amount"],
                        row["payment_count"],
                        Jsonb(row["raw"]),
                        row["classification"],
                    )
                )
        return
    pending = []
    for row in payments:
        pending.append(row)
        if len(pending) >= CHUNK_SIZE:
            bulk(db, Payment, pending)
    bulk(db, Payment, pending)


def demo_candidates(db, limit: int = 10):
    """Selection only; CL_TYPE never creates Membership or grants permissions."""
    return list(
        db.scalars(
            select(Company)
            .where(
                Company.client_type == "Client",
                Company.identity_quality == "confirmed",
                Company.is_placeholder.is_(False),
            )
            .order_by(Company.id)
            .limit(max(1, min(limit, 100)))
        )
    )

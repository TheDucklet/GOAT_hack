import csv
import hashlib
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Company, ImportBatch, Payment, PersonLink

COMPANIES_FILE = "df_Uid_data_hack.csv"
PEOPLE_FILE = "df_Fid_Uid_link_hack.csv"
PAYMENTS_FILE = "df_Uid_payment_hack.csv"
MISSING = {"", "nan", "None", "NULL", "null"}


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rows(path: Path, required: set[str]):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing columns in {path.name}: {sorted(required)}")
        for number, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f"Malformed row {number} in {path.name}")
            yield number, {k: v.strip() for k, v in row.items()}


def ident(value: str, number: int) -> str:
    if value in MISSING or len(value) > 100:
        raise ValueError(f"Invalid identifier at row {number}")
    return value


def bulk(db: Session, model, records, chunk_size=2000):
    for start in range(0, len(records), chunk_size):
        db.execute(insert(model), records[start : start + chunk_size])


def import_clients(db: Session, directory: Path) -> dict:
    """Atomically replace the active client snapshot; same file set is a no-op."""
    hashes = {name: file_hash(directory / name) for name in [COMPANIES_FILE, PEOPLE_FILE, PAYMENTS_FILE]}
    version = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(761202601)"))
    previous = db.get(ImportBatch, version)
    if previous and previous.active:
        return {**previous.report, "already_imported": True}

    grouped = defaultdict(list)
    all_ids = set()
    for number, row in rows(directory / COMPANIES_FILE, {"SYNTHETIC_U", "GROUP_ID"}):
        key = ident(row["SYNTHETIC_U"], number)
        grouped[key].append((number, row))
        all_ids.add(key)
    companies = []
    conflicts = []
    missing = defaultdict(int)
    for key, variants in grouped.items():
        features, unknowns = {}, []
        for field in variants[0][1]:
            if field == "SYNTHETIC_U":
                continue
            values = {r[field] for _, r in variants if r[field] not in MISSING}
            value = next(iter(values)) if len(values) == 1 else None
            if len(values) > 1:
                conflicts.append({"company_id": key, "field": field, "rows": [n for n, _ in variants]})
            if value is None:
                unknowns.append(field)
                missing[field] += 1
            features[field] = {
                "value": value,
                "source": {
                    "file": COMPANIES_FILE,
                    "field": field,
                    "rows": [n for n, _ in variants],
                    "file_sha256": hashes[COMPANIES_FILE],
                },
            }
        companies.append(
            {
                "id": key,
                "name": key,
                "group_id": features["GROUP_ID"]["value"],
                "features": features,
                "unknowns": unknowns,
                "profile_version": version,
                "is_placeholder": False,
            }
        )
    people = []
    seen_people = set()
    for number, row in rows(directory / PEOPLE_FILE, {"SYNTHETIC_F", "SYNTHETIC_U", "CITY_NAME", "RC_NAME"}):
        company_id = ident(row["SYNTHETIC_U"], number)
        person_id = ident(row["SYNTHETIC_F"], number)
        all_ids.add(company_id)
        key = (person_id, company_id, row["CITY_NAME"], row["RC_NAME"])
        if key not in seen_people:
            people.append(dict(zip(["person_id", "company_id", "city", "region"], key)))
            seen_people.add(key)
    payment_rows, total_amount, total_count = 0, Decimal(0), 0
    for number, row in rows(directory / PAYMENTS_FILE, {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}):
        all_ids.update([ident(row["PAYER"], number), ident(row["BENEFICIARY"], number)])
        amount, count = parse_payment(row, number)
        payment_rows += 1
        total_amount += amount
        total_count += count

    report = {
        "version": version,
        "files": hashes,
        "company_rows": sum(map(len, grouped.values())),
        "unique_companies": len(grouped),
        "conflicts": conflicts,
        "missing_fields": dict(missing),
        "person_links": len(people),
        "payment_rows": payment_rows,
        "payment_amount": str(total_amount),
        "payment_count": total_count,
        "placeholder_companies": len(all_ids - grouped.keys()),
        "already_imported": False,
    }
    # Only the active snapshot contributes payments. Old batch reports remain for provenance.
    db.execute(delete(Payment))
    db.execute(delete(PersonLink))
    db.execute(
        update(Company)
        .where(Company.profile_version != "demo-v1")
        .values(
            features={},
            unknowns=["profile_missing"],
            is_placeholder=True,
            group_id=None,
            profile_version=version,
        )
    )
    existing_ids = set(db.scalars(select(Company.id)))
    new_companies = []
    for company in companies:
        if company["id"] in existing_ids:
            db.execute(update(Company).where(Company.id == company["id"]).values(**company))
        else:
            new_companies.append(company)
    bulk(db, Company, new_companies)
    placeholders = [
        {
            "id": key,
            "name": key,
            "features": {},
            "unknowns": ["profile_missing"],
            "is_placeholder": True,
            "profile_version": version,
        }
        for key in all_ids - grouped.keys() - existing_ids
    ]
    bulk(db, Company, placeholders)
    db.execute(update(ImportBatch).values(active=False))
    if previous:
        previous.active, previous.report = True, report
    else:
        db.add(ImportBatch(id=version, report=report, active=True))
    db.flush()
    bulk(db, PersonLink, people)
    if db.bind.dialect.name == "postgresql":
        driver = db.connection().connection.driver_connection
        with (
            driver.cursor() as cursor,
            cursor.copy(
                "COPY payments (batch_id,row_number,payer,beneficiary,amount,payment_count) FROM STDIN"
            ) as copy,
        ):
            for number, row in rows(
                directory / PAYMENTS_FILE, {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}
            ):
                amount, count = parse_payment(row, number)
                copy.write_row((version, number, row["PAYER"], row["BENEFICIARY"], amount, count))
    else:
        pending = []
        for number, row in rows(directory / PAYMENTS_FILE, {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}):
            amount, count = parse_payment(row, number)
            pending.append(
                {
                    "batch_id": version,
                    "row_number": number,
                    "payer": row["PAYER"],
                    "beneficiary": row["BENEFICIARY"],
                    "amount": amount,
                    "payment_count": count,
                }
            )
            if len(pending) == 2000:
                db.execute(insert(Payment), pending)
                pending.clear()
        if pending:
            db.execute(insert(Payment), pending)
    if any(file_hash(directory / name) != sha for name, sha in hashes.items()):
        raise ValueError("Input files changed during import; transaction rolled back")
    return report


def parse_payment(row, number):
    try:
        amount, count = Decimal(row["PAY_AMT"]), Decimal(row["PAY_CNT"])
        if (
            not amount.is_finite()
            or not count.is_finite()
            or amount < 0
            or count <= 0
            or count != count.to_integral_value()
            or amount != amount.quantize(Decimal("0.01"))
        ):
            raise ValueError()
        return amount, int(count)
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"Invalid payment at row {number}") from exc


def company_context(db: Session, company_id: str) -> dict:
    company = db.get(Company, company_id)
    if not company:
        raise AppError(404, "not_found", "Компания не найдена")
    links = {}
    for direction, own, other in [
        ("outgoing", Payment.payer, Payment.beneficiary),
        ("incoming", Payment.beneficiary, Payment.payer),
    ]:
        statement = (
            select(other, func.sum(Payment.amount), func.sum(Payment.payment_count))
            .where(own == company_id)
            .group_by(other)
            .order_by(func.sum(Payment.amount).desc(), other)
            .limit(10)
        )
        links[direction] = [
            {
                "company_id": k,
                "amount": str(a),
                "payment_count": c,
                "source": {"table": "payments", "direction": direction},
            }
            for k, a, c in db.execute(statement)
        ]
    related = set()
    if company.group_id:
        related.update(
            db.scalars(
                select(Company.id)
                .where(
                    Company.group_id == company.group_id,
                    Company.id != company_id,
                )
                .limit(100)
            )
        )
    own_people = select(PersonLink.person_id).where(PersonLink.company_id == company_id)
    related.update(
        db.scalars(
            select(PersonLink.company_id)
            .where(
                PersonLink.person_id.in_(own_people),
                PersonLink.company_id != company_id,
            )
            .distinct()
            .limit(100)
        )
    )
    return {
        "company_id": company.id,
        "profile_version": company.profile_version,
        "group_id": company.group_id,
        "features": company.features,
        "unknowns": company.unknowns,
        "payment_links": links,
        "related_companies": sorted(related),
    }

"""Read-only CompanyContext v2; relation types never imply ownership or supply."""

from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.data_semantics import DATA_SEMANTICS_VERSION, confirmed_value
from app.errors import AppError
from app.models import Company, ImportBatch, Payment, PersonLink

RELATION_LIMIT = 100


def totals(db, *conditions):
    amount, count, rows = db.execute(
        select(func.sum(Payment.amount), func.sum(Payment.payment_count), func.count(Payment.id)).where(
            *conditions
        )
    ).one()
    return {
        "amount": format(amount or Decimal(0), ".2f"),
        "payment_count": int(count or 0),
        "row_count": rows,
    }


def payment_context(db, company_id):
    links = {}
    summary = {"unit": None, "period": None}
    active = db.scalar(select(ImportBatch).where(ImportBatch.active.is_(True)))
    provenance = {
        "table": "payments",
        "file": "df_Uid_payment_hack.csv",
        "batch_id": active.id if active else None,
        "file_sha256": active.report["files"].get("df_Uid_payment_hack.csv") if active else None,
        "semantics_version": DATA_SEMANTICS_VERSION,
    }
    for direction, own, other in [
        ("outgoing", Payment.payer, Payment.beneficiary),
        ("incoming", Payment.beneficiary, Payment.payer),
    ]:
        filters = [
            own == company_id,
            Payment.payer != Payment.beneficiary,
            Payment.classification == "external",
        ]
        summary[direction] = totals(db, *filters)
        statement = (
            select(
                other,
                func.sum(Payment.amount),
                func.sum(Payment.payment_count),
                func.count(Payment.id),
                Company.is_placeholder,
            )
            .join(Company, Company.id == other)
            .where(*filters)
            .group_by(other, Company.is_placeholder)
            .order_by(func.sum(Payment.amount).desc(), other)
            .limit(10)
        )
        links[direction] = [
            dict(
                company_id=key,
                amount=format(amount, ".2f"),
                payment_count=int(count),
                counterparty_status="placeholder" if placeholder else "known",
                unit=None,
                period=None,
                source={**provenance, "direction": direction, "row_count": rows},
            )
            for key, amount, count, rows, placeholder in db.execute(statement)
        ]
    summary["self_payments"] = totals(
        db, Payment.payer == company_id, Payment.beneficiary == company_id, Payment.classification == "self"
    )
    for label, classification in [("quarantined", "quarantined"), ("unclassified", "legacy")]:
        summary[label] = totals(
            db,
            or_(Payment.payer == company_id, Payment.beneficiary == company_id),
            Payment.classification == classification,
        )
    summary["provenance"] = provenance
    return links, summary


def group_summary(db, company):
    result = dict(
        group_id=company.group_id,
        observed_members=0,
        revenue_covered_members=0,
        revenue_sum=None,
        unit=None,
        period=None,
        is_consolidated=False,
        coverage_scope="observed_dataset",
    )
    if not company.group_id or company.identity_quality != "confirmed":
        return result
    # Fetch only the needed JSON fragment, not entire company profiles.
    rows = list(
        db.execute(
            select(Company.features["REVENUE_COMPANY"]).where(
                Company.group_id == company.group_id,
                Company.identity_quality == "confirmed",
                Company.is_placeholder.is_(False),
            )
        )
    )
    result["observed_members"] = len(rows)
    covered = [
        entry
        for (entry,) in rows
        if entry and confirmed_value(entry) is not None and entry.get("unit") and entry.get("period")
    ]
    result["revenue_covered_members"] = len(covered)
    bases = {(entry["unit"], entry["period"]) for entry in covered}
    if covered and len(bases) == 1:
        result["unit"], result["period"] = next(iter(bases))
        result["revenue_sum"] = str(sum((Decimal(entry["value"]) for entry in covered), Decimal(0)))
    return result


def relationship_context(db, company):
    relationships, coverage = (
        [],
        {"limit_per_relation": RELATION_LIMIT, "group_truncated": False, "person_truncated": False},
    )
    if company.identity_quality != "confirmed":
        return relationships, coverage
    if company.group_id:
        peers = list(
            db.scalars(
                select(Company.id)
                .where(
                    Company.group_id == company.group_id,
                    Company.id != company.id,
                    Company.identity_quality == "confirmed",
                    Company.is_placeholder.is_(False),
                )
                .order_by(Company.id)
                .limit(RELATION_LIMIT + 1)
            )
        )
        coverage["group_truncated"] = len(peers) > RELATION_LIMIT
        relationships.extend(
            dict(
                company_id=peer,
                relation_type="same_group",
                provenance={
                    "field": "GROUP_ID",
                    "group_id": company.group_id,
                    "source": company.features["GROUP_ID"]["provenance"],
                },
            )
            for peer in peers[:RELATION_LIMIT]
        )
    own, other = aliased(PersonLink), aliased(PersonLink)
    peers = list(
        db.execute(
            select(other.company_id, other.person_id, own.provenance, other.provenance)
            .join(own, own.person_id == other.person_id)
            .join(Company, Company.id == other.company_id)
            .where(
                own.company_id == company.id,
                other.company_id != company.id,
                Company.identity_quality.in_(["confirmed", "placeholder"]),
            )
            .order_by(other.company_id, other.person_id, own.id, other.id)
            .limit(RELATION_LIMIT + 1)
        )
    )
    coverage["person_truncated"] = len(peers) > RELATION_LIMIT
    relationships.extend(
        dict(
            company_id=peer,
            relation_type="shared_person",
            provenance={"person_id": person, "own_link": own_source, "other_link": other_source},
        )
        for peer, person, own_source, other_source in peers[:RELATION_LIMIT]
    )
    return relationships, coverage


def company_context(db, company_id: str) -> dict:
    company = db.get(Company, company_id)
    if not company:
        raise AppError(404, "not_found", "Компания не найдена")
    features = company.features
    if company.data_semantics_version != DATA_SEMANTICS_VERSION:
        # Migration cannot manufacture raw provenance or retroactively confirm meaning.
        features = {
            field: {
                "raw": [str(entry.get("value", ""))],
                "normalized": None,
                "value": None,
                "quality": "legacy",
                "issues": ["source_reimport_required"],
                "unit": None,
                "period": None,
                "provenance": entry.get("source", {}),
            }
            for field, entry in features.items()
        }
    links, payments = payment_context(db, company.id)
    relationships, coverage = relationship_context(db, company)
    related = sorted({item["company_id"] for item in relationships})
    for direction, items in links.items():
        relationships.extend(
            dict(
                company_id=item["company_id"],
                relation_type="payment",
                direction=direction,
                provenance=item["source"],
            )
            for item in items
        )
    unknowns = set(company.unknowns) | {"payment_period", "payment_currency"}
    if "REVENUE_COMPANY" in features and confirmed_value(features["REVENUE_COMPANY"]) is None:
        unknowns.update(["revenue_currency", "revenue_reporting_year"])
    if confirmed_value(features.get("FTS_FLAG")) == "1" or confirmed_value(features.get("FTS_COUNTRY_NAME")):
        unknowns.add("trade_direction")
    if company.identity_quality == "legacy":
        unknowns.add("source_reimport_required")
    return dict(
        schema_version="v2",
        data_semantics_version=company.data_semantics_version,
        company_id=company.id,
        profile_version=company.profile_version,
        group_id=company.group_id,
        features=features,
        unknowns=sorted(unknowns),
        identity_quality=company.identity_quality,
        client_type=company.client_type,
        payment_links=links,
        payment_summary=payments,
        related_companies=related,
        relationships=relationships,
        relationship_coverage=coverage,
        group_summary=group_summary(db, company),
    )

"""Versioned CSV meaning and conservative normalization, without I/O or LLM calls."""

import re
from decimal import Decimal, InvalidOperation

DATA_SEMANTICS_VERSION = "company-data-2"
LEGACY_SEMANTICS_VERSION = "legacy-company-1"
COMPANIES_FILE = "df_Uid_data_hack.csv"
PEOPLE_FILE = "df_Fid_Uid_link_hack.csv"
PAYMENTS_FILE = "df_Uid_payment_hack.csv"
MISSING = {"", "nan", "none", "null"}
CLIENT_TYPES = {
    "CLIENT": "Client",
    "PROSPECT": "Prospect",
    "CLOSE_CLIENT": "Closed Client",
    "CLOSED CLIENT": "Closed Client",
    "CLOSED_CLIENT": "Closed Client",
}
FLAGS = {"NEGATIVEMARK", "FTS_FLAG", "FACTORING_MARK"}


def clean(value: str) -> str | None:
    value = value.strip()
    return None if value.casefold() in MISSING else value


def suspicious_id(value: str) -> bool:
    return value.casefold() in {"unknown", "undefined", "common", "-1", "общий"} or bool(
        re.fullmatch(r"0+(?:-0+)*", value)
    )


def ambiguous_identity(company_id: str, variants: list[tuple[int, dict]]) -> bool:
    # A heuristic, not a claim that a specific ID denotes several legal entities.
    # Ordinary repeats or one conflicting field do not trigger identity quarantine.
    cities = {clean(row.get("CITY", "")) for _, row in variants} - {None}
    industries = {clean(row.get("MAINOKVED_CODE", "")) for _, row in variants} - {None}
    return suspicious_id(company_id) or (len(cities) > 1 and len(industries) > 1)


def normalize_value(field: str, raw: str) -> tuple[str | None, list[str]]:
    value = clean(raw)
    if value is None:
        return None, []
    if field in FLAGS or field.startswith("CL_PRODUCT_"):
        if value.casefold() in {"1", "1.0", "true"}:
            return "1", []
        if value.casefold() in {"0", "0.0", "false"}:
            return "0", []
        return None, ["invalid_binary_flag"]
    if field == "CL_TYPE":
        return CLIENT_TYPES.get(value.upper()), [] if value.upper() in CLIENT_TYPES else [
            "unknown_client_type"
        ]
    if field == "REVENUE_COMPANY":
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation()
            issues = ["currency_unknown", "reporting_year_unknown"]
            if amount == 1000:
                issues.append("possible_placeholder_1000_unconfirmed")
            return format(amount.normalize(), "f"), issues
        except InvalidOperation:
            return None, ["invalid_revenue"]
    return value, []


def normalize_feature(
    field: str, variants: list[tuple[int, dict]], sha: str, quarantined: bool = False
) -> dict:
    parsed = [normalize_value(field, row.get(field, "")) for _, row in variants]
    values = {value for value, _ in parsed if value is not None}
    issues = sorted({issue for _, problems in parsed for issue in problems})
    normalized = next(iter(values)) if len(values) == 1 else None
    quality = "confirmed"
    if not values:
        quality = "invalid" if issues else "missing"
    if len(values) > 1:
        quality, normalized = "conflicting", None
    elif issues:
        quality = "assumed" if field == "REVENUE_COMPANY" and normalized is not None else "invalid"
    if quarantined:
        quality = "quarantined"
        issues.append("ambiguous_company_identity")
    return {
        "raw": [row.get(field, "") for _, row in variants],
        "normalized": normalized,
        # Compatibility projection: uncertain data can never become a legacy AI fact.
        "value": normalized if quality == "confirmed" else None,
        "quality": quality,
        "issues": issues,
        "unit": None,
        "period": "annual_year_unknown" if field == "REVENUE_COMPANY" else None,
        "provenance": {
            "file": COMPANIES_FILE,
            "field": field,
            "rows": [n for n, _ in variants],
            "file_sha256": sha,
            "semantics_version": DATA_SEMANTICS_VERSION,
        },
    }


def confirmed_value(entry: dict | None):
    if not entry or entry.get("quality", "confirmed") != "confirmed":
        return None
    return entry.get("value")

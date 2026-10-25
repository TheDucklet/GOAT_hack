from datetime import date

from app.ai.impact.dates import parse_iso
from app.ai.rag.temporal import CURRENT_DAYS
from app.notice_policy import DISCLAIMER, POLICY_VERSION

BANK_CURRENT_DAYS = CURRENT_DAYS
HYPOTHESIS_SECTIONS = ("ai_interpretation", "risks", "opportunities", "actions")
RELEVANCE_STATUSES = ("active", "review_required", "expired", "undetermined")


def statement(claim_id: str, text: str, refs: list[str], kind: str) -> dict:
    return {
        "claim_id": claim_id,
        "text": text,
        "evidence_refs": list(dict.fromkeys(refs)),
        "statement_type": kind,
    }


def typed_sections(v1_result: dict, bank_view: list[dict] | None) -> dict:
    sections = {
        "facts": [
            statement(c["claim_id"], c["text"], c["evidence_refs"], "fact") for c in v1_result["facts"]
        ],
        "bank_view": None
        if not bank_view
        else [statement(c["claim_id"], c["text"], c["evidence_refs"], "fact") for c in bank_view],
    }
    for name in HYPOTHESIS_SECTIONS:
        sections[name] = [
            statement(c["claim_id"], c["text"], c["evidence_refs"], "hypothesis") for c in v1_result[name]
        ]
    return sections


def split_bank_view(claims: list[dict] | None, evidence: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    dated, undated = [], []
    for claim in claims or []:
        refs = claim["evidence_refs"]
        if refs and all(parse_iso(evidence[ref]["locator"].get("document_date")) for ref in refs):
            dated.append(claim)
        else:
            undated.append(claim)
    return dated, undated


def bank_context(bank_view: list[dict] | None, evidence: dict[str, dict], event_day: date) -> dict:
    if not bank_view:
        return {"status": "missing", "document_dates": []}
    dates = sorted(
        {
            parse_iso(evidence[ref]["locator"]["document_date"])
            for claim in bank_view
            for ref in claim["evidence_refs"]
        }
    )
    status = "historical" if (event_day - dates[-1]).days > BANK_CURRENT_DAYS else "current"
    return {"status": status, "document_dates": [item.isoformat() for item in dates]}


def relevance_window(
    kind: str, starts_on: date | None, ends_on: date | None, event_day: date, today: date, determined: bool
) -> dict:
    empty = {
        "relevance_status": "undetermined",
        "valid_from": None,
        "valid_until": None,
        "review_after": None,
    }
    if not determined:
        return empty
    if kind == "long_term":
        return {
            "relevance_status": "active",
            "valid_from": event_day,
            "valid_until": None,
            "review_after": None,
        }
    if kind != "dated" or not (starts_on or ends_on):
        return empty
    review = ends_on or (starts_on if starts_on and starts_on > event_day else None)
    valid_until = ends_on
    status = "active"
    if valid_until and today > valid_until:
        status = "expired"
    elif review and today >= review:
        status = "review_required"
    valid_from = min(event_day, starts_on) if starts_on else event_day
    if valid_until and valid_until < valid_from:
        return empty
    return {
        "relevance_status": status,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "review_after": review
        if review and review >= valid_from and (valid_until is None or review <= valid_until)
        else None,
    }


def next_actions(determined: bool) -> list[dict]:
    question = (
        "Какие данные нужно уточнить, чтобы проверить это влияние на моей компании?"
        if determined
        else "Каких данных не хватает, чтобы оценить влияние события на мою компанию?"
    )
    return [
        {"action": "ask_question", "label": "Уточнить недостающие данные", "question": question},
        {"action": "contact_manager_demo", "label": "Связаться с менеджером (демо)", "question": None},
        {"action": "hide_insight", "label": "Скрыть", "question": None},
    ]


def policy_fields() -> dict:
    return {"policy_version": POLICY_VERSION, "disclaimer": DISCLAIMER}

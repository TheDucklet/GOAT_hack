import re

from app.ai.insights.context import company_facts
from app.ai.summarization.grounding import unsupported_numbers
from app.ai.summarization.vocabulary import THEMES

CLAIM_SECTIONS = ("facts", "ai_interpretation", "risks", "opportunities", "actions")
CONFLICT_WORDS = re.compile(
    r"расходя|расхожд|различ|противореч|по-разному|разные|не совпада|не согласу", re.IGNORECASE
)
MISSING_DATA_WORDS = re.compile(
    r"выручк|кредит|депозит|продукт|профил|сведен|данн|долг|задолж|неизвестн|структур", re.IGNORECASE
)
BANK_UNKNOWN_WORDS = re.compile(r"банк", re.IGNORECASE)


def check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def claims_of(result: dict, sections=CLAIM_SECTIONS) -> list[dict]:
    claims = [claim for section in sections for claim in result.get(section) or []]
    return claims + list(result.get("bank_view") or [])


def source_text(event: dict, company: dict, envelope: dict) -> str:
    parts = [event["title"], event.get("summary") or ""]
    parts += [publication["text"] for publication in event["publications"]]
    parts += [fact.excerpt + " " + fact.value for fact in company_facts(company)]
    parts += [item["excerpt"] for item in envelope["evidence"]]
    return " ".join(parts)


def refs_resolve(envelope: dict, event: dict) -> dict:
    known = {item["id"] for item in event["evidence"]} | {item["id"] for item in envelope["evidence"]}
    claims = claims_of(envelope["result"])
    missing = sorted({ref for claim in claims for ref in claim["evidence_refs"]} - known)
    without_refs = [claim["claim_id"] for claim in claims if not claim["evidence_refs"]]
    return check(
        "refs_resolve",
        not missing and not without_refs,
        f"неизвестные ссылки: {missing}, утверждения без ссылок: {without_refs}",
    )


def numbers_grounded(envelope: dict, event: dict, company: dict) -> dict:
    sources = source_text(event, company, envelope)
    ungrounded = {
        claim["claim_id"]: sorted(unsupported_numbers(claim["text"], sources))
        for claim in claims_of(envelope["result"])
        if unsupported_numbers(claim["text"], sources)
    }
    return check("numbers_grounded", not ungrounded, f"числа без источника: {ungrounded}")


def company_scope(envelope: dict, company: dict) -> dict:
    foreign = [
        item["id"]
        for item in envelope["evidence"]
        if item["kind"] == "company" and item["source_id"] != company["company_id"]
    ]
    return check("company_scope", not foreign, f"чужие источники компании: {foreign}")


def bank_view_rule(envelope: dict) -> dict:
    kinds = {item["id"]: item["kind"] for item in envelope["evidence"]}
    wrong = [
        claim["claim_id"]
        for claim in envelope["result"].get("bank_view") or []
        if any(kinds.get(ref, "bank") != "bank" for ref in claim["evidence_refs"])
    ]
    return check("bank_view_only_bank_evidence", not wrong, f"позиция банка ссылается не на банк: {wrong}")


def validation_clean(envelope: dict) -> dict:
    report = envelope["trace"].get("validation") or {}
    contradicted = {
        item["claim_id"] for item in report.get("claims", []) if item["verdict"] == "contradiction"
    }
    published = {claim["claim_id"] for claim in claims_of(envelope["result"])}
    remaining = sorted(contradicted & published)
    return check(
        "no_contradiction_in_published_card",
        not remaining,
        f"противоречия в карточке: {remaining}, перехвачено проверкой и убрано: {len(contradicted) - len(remaining)}",
    )


def card_not_empty(envelope: dict) -> dict:
    result = envelope["result"]
    useful = [
        section for section in ("ai_interpretation", "risks", "opportunities", "actions") if result[section]
    ]
    return check(
        "card_has_facts_and_analysis",
        bool(result["facts"]) and bool(useful),
        f"факты: {len(result['facts'])}, разделы анализа: {useful}",
    )


def base_checks(envelope: dict, event: dict, company: dict) -> list[dict]:
    return [
        refs_resolve(envelope, event),
        numbers_grounded(envelope, event, company),
        company_scope(envelope, company),
        bank_view_rule(envelope),
        validation_clean(envelope),
        card_not_empty(envelope),
    ]


def themes_canonical(focus: dict, interests: list[str]) -> dict:
    outside = [topic for topic in focus["topics"] if topic not in THEMES and topic not in interests]
    return check(
        "focus_topics_from_vocabulary_or_own_interests",
        not outside,
        f"темы вне словаря и интересов: {outside}",
    )


def verdict_of(checks: list[dict]) -> str:
    return "PASS" if all(item["ok"] for item in checks) else "FAIL"

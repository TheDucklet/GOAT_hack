from app.ai.summarization.grounding import shorten
from app.ai.validation.catalog import Catalog
from app.ai.validation.checks import CONTRADICTION, INSUFFICIENT, SUPPORTED, check_claim

VALIDATION_VERSION = "validation-1"
CLAIM_SECTIONS = ("facts", "bank_view", "ai_interpretation", "risks", "opportunities", "actions")
MAX_REMOVED_UNKNOWNS = 4
MAX_TEXT_PREVIEW = 90
NO_BANK_UNKNOWN = "Нет подтверждающих материалов банка на дату события"
NO_FACTS_UNKNOWN = "Источников недостаточно для вывода о влиянии события на компанию"


def claim_record(claim: dict, section: str, verdict: str, problems, statuses: dict[str, str]) -> dict:
    return {
        "claim_id": claim["claim_id"],
        "section": section,
        "verdict": verdict,
        "reasons": [{"code": item.code, "detail": item.detail} for item in problems],
        "evidence": [{"id": ref, "status": status} for ref, status in statuses.items()],
    }


def validate_result(result: dict, evidence: list[dict], catalog: Catalog) -> dict:
    evidence_by_id = {**catalog.news, **{item["id"]: item for item in evidence}}
    kept: dict[str, list[dict]] = {}
    records: list[dict] = []
    removed: list[dict] = []
    for section in CLAIM_SECTIONS:
        kept[section] = []
        for claim in result.get(section) or []:
            verdict, problems, valid_refs, statuses = check_claim(claim, section, evidence_by_id, catalog)
            records.append(claim_record(claim, section, verdict, problems, statuses))
            if verdict == SUPPORTED:
                kept[section].append({**claim, "evidence_refs": valid_refs})
            else:
                removed.append({"claim": claim, "section": section, "verdict": verdict, "problems": problems})
    counts = {
        name: sum(1 for item in records if item["verdict"] == name)
        for name in (SUPPORTED, INSUFFICIENT, CONTRADICTION)
    }
    report = {
        "claims": records,
        "summary": {**counts, "removed": len(removed), "publishable": not removed},
        "removed_claims": [
            {"claim_id": item["claim"]["claim_id"], "section": item["section"], "verdict": item["verdict"]}
            for item in removed
        ],
    }
    return {"kept": kept, "report": report, "removed": removed}


def validate_envelope(envelope: dict, catalog: Catalog) -> dict:
    return validate_result(envelope["result"], envelope.get("evidence", []), catalog)["report"]


def removal_unknowns(removed: list[dict]) -> list[str]:
    notes = []
    for item in removed[:MAX_REMOVED_UNKNOWNS]:
        preview = shorten(item["claim"]["text"], MAX_TEXT_PREVIEW)
        codes = ", ".join(sorted({problem.code for problem in item["problems"]}))
        notes.append(f"Утверждение не прошло проверку оснований и убрано из карточки ({codes}): «{preview}»")
    if len(removed) > MAX_REMOVED_UNKNOWNS:
        notes.append(f"Ещё утверждений убрано при проверке оснований: {len(removed) - MAX_REMOVED_UNKNOWNS}")
    return notes


def apply_validation(envelope: dict, catalog: Catalog) -> tuple[dict, dict]:
    result = envelope["result"]
    outcome = validate_result(result, envelope.get("evidence", []), catalog)
    kept, removed = outcome["kept"], outcome["removed"]
    bank_view = kept["bank_view"] or None
    unknowns = list(result["unknowns"])
    if bank_view is None and result.get("bank_view") and NO_BANK_UNKNOWN not in unknowns:
        unknowns.append(NO_BANK_UNKNOWN)
    unknowns.extend(note for note in removal_unknowns(removed) if note not in unknowns)
    if not kept["facts"] and NO_FACTS_UNKNOWN not in unknowns:
        unknowns.insert(0, NO_FACTS_UNKNOWN)
    claims = [claim for section in CLAIM_SECTIONS for claim in kept[section]]
    refs = list(dict.fromkeys(ref for claim in claims for ref in claim["evidence_refs"]))
    new_result = {
        **result,
        **{section: kept[section] for section in CLAIM_SECTIONS if section != "bank_view"},
        "bank_view": bank_view,
        "unknowns": unknowns,
        "evidence_refs": refs,
    }
    evidence = [item for item in envelope.get("evidence", []) if item["id"] in set(refs)]
    return {**envelope, "result": new_result, "evidence": evidence}, outcome["report"]


def validate_answer(
    answer: str, refs: list[str], evidence: list[dict], catalog: Catalog, extra_support: str = ""
) -> dict:
    evidence_by_id = {**catalog.news, **{item["id"]: item for item in evidence}}
    claim = {"claim_id": "answer", "text": answer, "evidence_refs": refs}
    verdict, problems, valid_refs, statuses = check_claim(
        claim, "answer", evidence_by_id, catalog, extra_support
    )
    return {
        "verdict": verdict,
        "valid_refs": valid_refs,
        "record": claim_record(claim, "answer", verdict, problems, statuses),
    }

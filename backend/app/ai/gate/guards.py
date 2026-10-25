import re

from app.ai.rag.search import stem
from app.ai.summarization.grounding import normalize_text

BANK_COVERAGE_THRESHOLD = 0.8
MIN_WORD_CHARS = 4


def stems_of(text: str) -> set[str]:
    words = re.findall(r"[а-яa-z0-9]+", normalize_text(text))
    return {stem(word) for word in words if len(word) >= MIN_WORD_CHARS}


def bank_coverage(claim: str, fragments: list[str]) -> float:
    wanted = stems_of(claim)
    if not wanted:
        return 1.0
    have = set().union(*(stems_of(item) for item in fragments)) if fragments else set()
    return len(wanted & have) / len(wanted)


def apply_bank_guard(
    claims: list[dict], sources: dict[str, dict], verdicts: dict[str, dict]
) -> dict[str, dict]:
    for claim in claims:
        if claim["section"] != "bank_view" or verdicts[claim["claim_id"]]["verdict"] != "supported":
            continue
        fragments = [
            sources[ref]["text"]
            for ref in claim["evidence_refs"]
            if ref in sources and sources[ref]["kind"] == "bank"
        ]
        coverage = bank_coverage(claim["text"], fragments)
        if coverage < BANK_COVERAGE_THRESHOLD:
            verdicts[claim["claim_id"]] = {
                "verdict": "unsupported",
                "reason": f"в утверждении банка только {round(coverage * 100)} % слов опираются на банковский фрагмент",
            }
    return verdicts

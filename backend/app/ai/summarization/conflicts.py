import re
from itertools import combinations

from app.ai.rag.search import stem
from app.ai.summarization.grounding import shorten

NUMBER_WITH_UNIT = re.compile(
    r"(?<![\w.,])(\d+(?:\s\d{3})*(?:[.,]\d+)?)\s*(%|[а-яё]+\.?(?:\s+[а-яё]+\.?)?)", re.IGNORECASE
)
DIGITS = re.compile(r"\d[\d\s.,]*")
WORD = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)
MAGNITUDES = ("млн", "млрд", "трлн", "тыс")
UNITS = ("%", "руб", "тонн", "долл", "евро", "юан", "п.п", "б.п", *MAGNITUDES)
MIN_SHARED_STEMS = 3
MIN_OVERLAP = 0.3
PREVIEW_CHARS = 70


def unit_key(unit: str) -> str | None:
    words = unit.lower().split()
    if not words:
        return None
    first = words[0].rstrip(".")
    if first != "%" and not first.startswith(UNITS):
        return None
    if first.startswith(MAGNITUDES) and len(words) > 1:
        return f"{first[:3]} {words[1].rstrip('.')[:3]}"
    return "%" if first == "%" else first[:3]


def quantities(text: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for match in NUMBER_WITH_UNIT.finditer(text):
        key = unit_key(match.group(2))
        if key is None:
            continue
        value = re.sub(r"\s", "", match.group(1)).replace(",", ".")
        found.setdefault(key, set()).add(value)
    return found


def context_stems(text: str) -> set[str]:
    return {stem(word.lower()) for word in WORD.findall(DIGITS.sub(" ", text))}


def similar_context(first: str, second: str) -> bool:
    left, right = context_stems(first), context_stems(second)
    shared = left & right
    return len(shared) >= MIN_SHARED_STEMS and len(shared) / len(left | right) >= MIN_OVERLAP


def source_conflicts(facts: list[dict]) -> list[str]:
    notes = []
    for first, second in combinations(facts, 2):
        if set(first["evidence_refs"]) & set(second["evidence_refs"]):
            continue
        if not similar_context(first["text"], second["text"]):
            continue
        left, right = quantities(first["text"]), quantities(second["text"])
        if any(left[key] != right[key] for key in left.keys() & right.keys()):
            notes.append(
                "Источники события расходятся в данных: "
                f"«{shorten(first['text'], PREVIEW_CHARS)}» и «{shorten(second['text'], PREVIEW_CHARS)}»"
            )
    return list(dict.fromkeys(notes))

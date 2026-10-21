import math
import re
from datetime import date
from itertools import combinations

from app.ai.schemas import BankSearchResult, SearchBankAnalyticsInput

MAX_QUERY_TERMS = 8
MIN_TERM_CHARS = 2
REQUIRED_COVERAGE = 0.6
MAX_VARIANTS = 40
STEM_CHARS = 5
EXCERPT_CHARS = 320
HISTORICAL_AFTER_DAYS = 365
CANDIDATES_PER_VARIANT = 20
WORD = re.compile(r"[0-9a-zа-яё]+(?:[,.][0-9]+)?", re.IGNORECASE)

STOP_WORDS = frozenset(
    "и в во на не что как а но по за из от до для при под над без про это эти этот эта или же ли "
    "бы то так там тут все всё его её их мы вы они он она оно был была были быть есть будет "
    "какой какая какие каков какова каковы где когда почему зачем сколько также еще ещё уже "
    "наш наша наши нашей нам нас вам ваш ваша ваши какое каком какую какими который которая которое которые которых".split()
)


def stem(word: str) -> str:
    return word[:STEM_CHARS] if len(word) > STEM_CHARS else word


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for match in WORD.finditer(query.lower()):
        word = match.group(0)
        if word in STOP_WORDS or (len(word) < MIN_TERM_CHARS and not word[0].isdigit()):
            continue
        if word not in terms:
            terms.append(word)
    return terms[:MAX_QUERY_TERMS]


def search_variants(query: str, terms: list[str]) -> list[str]:
    if not terms:
        return [query.strip()]
    groups: list[tuple[str, ...]] = []
    if len(terms) > 1:
        groups.append(tuple(terms))
    if len(terms) > 3:
        groups.extend(combinations(terms, len(terms) - 1))
    groups.extend(combinations(terms, 2))
    groups.extend((term,) for term in terms)
    variants: list[str] = []
    for group in groups:
        variant = " ".join(group)
        if variant not in variants:
            variants.append(variant)
    return variants[:MAX_VARIANTS]


def required_terms(terms: list[str]) -> int:
    return 1 if len(terms) <= 1 else math.ceil(len(terms) * REQUIRED_COVERAGE)


def term_stems_in(text: str, terms: list[str]) -> dict[str, int]:
    lowered = text.lower()
    return {term: lowered.count(stem(term)) for term in terms if stem(term) in lowered}


def score_candidates(candidates: list[dict], terms: list[str]) -> list[tuple[float, dict]]:
    counts = [term_stems_in(candidate["text"], terms) for candidate in candidates]
    total = max(1, len(candidates))
    document_frequency = {term: sum(1 for found in counts if term in found) for term in terms}
    scored = []
    required = required_terms(terms)
    for candidate, found in zip(candidates, counts, strict=True):
        if len(found) < required:
            continue
        weight = sum(
            math.log(1 + total / document_frequency[term]) * (1 + math.log(found[term])) for term in found
        )
        coverage = len(found) / max(1, len(terms))
        scored.append((weight * (0.5 + coverage * coverage), candidate))
    return sorted(scored, key=lambda item: (-item[0], item[1]["page"], item[1]["chunk_id"]))


def excerpt_for(text: str, terms: list[str]) -> str:
    text = text.strip()
    if len(text) <= EXCERPT_CHARS:
        return text
    lowered = text.lower()
    positions = sorted(
        position for position in (lowered.find(stem(term)) for term in terms) if position != -1
    )
    anchor = (
        max(
            positions,
            key=lambda first: sum(1 for other in positions if first <= other < first + EXCERPT_CHARS),
        )
        if positions
        else 0
    )
    start = max(0, anchor - EXCERPT_CHARS // 6)
    if start:
        start = text.find(" ", start) + 1 or start
    end = min(len(text), start + EXCERPT_CHARS)
    if end < len(text):
        cut = text.rfind(" ", start, end)
        end = cut if cut > start else end
    return text[start:end].strip()


def is_historical(document_date: str | None, as_of: date) -> bool:
    if not document_date:
        return False
    return (as_of - date.fromisoformat(document_date)).days > HISTORICAL_AFTER_DAYS


def search_bank_analytics(query: str, as_of: str, limit: int, repository) -> dict:
    request = SearchBankAnalyticsInput.model_validate({"query": query, "as_of": as_of, "limit": limit})
    terms = query_terms(request.query)
    candidates: dict[str, dict] = {}
    for variant in search_variants(request.query, terms):
        for chunk in repository.search_chunks(variant, request.as_of.isoformat(), CANDIDATES_PER_VARIANT):
            if chunk["document_date"] and chunk["document_date"] > request.as_of.isoformat():
                continue
            candidates.setdefault(chunk["chunk_id"], chunk)
    ranked = score_candidates(list(candidates.values()), terms)[: request.limit]
    items = [
        {
            "chunk_id": chunk["chunk_id"],
            "document_id": chunk["document_id"],
            "version": chunk["version"],
            "index_version": chunk["index_version"],
            "page": chunk["page"],
            "document_date": chunk["document_date"],
            "date_unknown": chunk["document_date"] is None,
            "historical": is_historical(chunk["document_date"], request.as_of),
            "text": chunk["text"],
            "excerpt": excerpt_for(chunk["text"], terms),
            "locator": {"page": chunk["page"]},
            "score": round(score, 4),
        }
        for score, chunk in ranked
    ]
    reason = (
        None
        if items
        else f"В проиндексированных документах нет фрагментов по запросу на дату {request.as_of}"
    )
    return BankSearchResult.model_validate(
        {"items": items, "query": request.query, "as_of": request.as_of.isoformat(), "empty_reason": reason}
    ).model_dump(mode="json")

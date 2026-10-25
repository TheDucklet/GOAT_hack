from dataclasses import dataclass
from typing import Annotated

from pydantic import BeforeValidator, Field

from app.ai.gate.verify import verify_claims
from app.ai.lenient import Lenient, StrList, to_dict_list
from app.ai.providers import LLMInput, call_llm
from app.ai.rag.search import stem
from app.ai.schemas import EventPayload, GroundedSummaryResult, SummarizeEventInput
from app.ai.summarization.conditions import condition_sentences
from app.ai.summarization.grounding import (
    SENTENCE_END,
    context_sentence,
    normalize_text,
    quote_in_source,
    strip_instructions,
    supported_sentences,
    unsupported_direction,
    unsupported_numbers,
)
from app.ai.summarization.industries import select_industries
from app.ai.summarization.prompts import FACT_CHECK_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT
from app.ai.summarization.vocabulary import (
    PRODUCT_FLAGS,
    canonical,
    canonical_themes,
    match_countries,
    match_industries,
    match_regions,
    products_for_themes,
)

MAX_PUBLICATIONS = 5
PUBLICATION_CHARS = 6000
MAX_FACTS = 6
MAX_ENTITIES = 15
MAX_TOKENS = 2200
RETRY_TEMPERATURE = 0.3
ATTEMPTS = 2
FACT_CHECK_TASK = "verify_event_facts"


class RawFact(Lenient):
    text: str = ""
    quote: str = ""
    source: str = ""


class RawTopics(Lenient):
    theme: StrList = Field(default_factory=list)
    industry_keywords: StrList = Field(default_factory=list)
    regions: StrList = Field(default_factory=list)
    countries: StrList = Field(default_factory=list)
    products: StrList = Field(default_factory=list)


class RawSummary(Lenient):
    summary: str = ""
    facts: Annotated[list[RawFact], BeforeValidator(to_dict_list)] = Field(default_factory=list)
    entities: StrList = Field(default_factory=list)
    topics: RawTopics = Field(default_factory=RawTopics)


@dataclass(frozen=True)
class Source:
    label: str
    url: str
    evidence_id: str
    text: str


def sources_of(event: EventPayload) -> list[Source]:
    evidence_by_publication = {item.source_id: item.id for item in event.evidence if item.kind == "news"}
    sources = []
    for publication in event.publications:
        evidence_id = evidence_by_publication.get(publication.id)
        text = strip_instructions(publication.text)
        if evidence_id and text:
            label = f"P{len(sources) + 1}"
            sources.append(Source(label, publication.url, evidence_id, text[:PUBLICATION_CHARS]))
        if len(sources) == MAX_PUBLICATIONS:
            break
    return sources


def build_prompt(event: EventPayload, sources: list[Source]) -> str:
    parts = [f"Заголовок события: {event.title}"]
    if event.published_at:
        parts.append(f"Дата публикации: {event.published_at}")
    for source in sources:
        parts.append(f"[{source.label}] {source.url}\n<<<\n{source.text}\n>>>")
    return "\n\n".join(parts)


def verified_facts(
    raw_facts: list[RawFact], sources: list[Source], rejected: list[dict] | None = None
) -> list[dict]:
    by_label = {source.label: source for source in sources}
    facts, seen = [], set()
    for raw in raw_facts:
        text = raw.text.strip()
        candidates = [by_label[raw.source]] if raw.source in by_label else sources
        source = next((item for item in candidates if quote_in_source(raw.quote, item.text)), None)
        if not text or source is None or unsupported_numbers(text, source.text):
            continue
        direction = unsupported_direction(text, context_sentence(raw.quote, source.text))
        if direction:
            if rejected is not None:
                rejected.append(
                    {
                        "text": text,
                        "stage": "direction_guard",
                        "reason": "направление изменения: " + ", ".join(sorted(direction)),
                    }
                )
            continue
        key = normalize_text(text)
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            {"claim_id": f"fact-{len(facts) + 1}", "text": text, "evidence_refs": [source.evidence_id]}
        )
        if len(facts) == MAX_FACTS:
            break
    return facts


def verified_entities(entities: list[str], sources: list[Source]) -> list[str]:
    haystack = normalize_text(" ".join(source.text for source in sources))
    kept: list[str] = []
    for entity in entities:
        words = [stem(word) for word in normalize_text(entity).split() if len(word) > 2]
        if words and all(word in haystack for word in words) and entity.strip() not in kept:
            kept.append(entity.strip())
    return kept[:MAX_ENTITIES]


def topics_of(raw: RawTopics, news_text: str) -> dict[str, list[str]]:
    themes = canonical_themes(raw.theme)
    geo = match_regions(raw.regions) + match_countries(raw.countries)
    products = canonical(raw.products, PRODUCT_FLAGS) + products_for_themes(themes)
    return {
        "theme": themes,
        "industry": select_industries(match_industries(raw.industry_keywords), news_text),
        "product": list(dict.fromkeys(products)),
        "geo": list(dict.fromkeys(geo)),
        "relation": [],
    }


def summary_text(raw: RawSummary, facts: list[dict], sources: list[Source], title: str) -> str:
    supported = supported_sentences(raw.summary, " ".join(source.text for source in sources) + " " + title)
    if supported:
        return supported
    return facts[0]["text"] if facts else title


def checked_facts_and_summary(
    facts: list[dict], summary: str, sources: list[Source], rejected: list[dict], usage: list[dict]
) -> tuple[list[dict], str]:
    by_evidence = {source.evidence_id: source for source in sources}
    sentences = [part for part in SENTENCE_END.split(summary.strip()) if part]
    claims = [
        {
            "claim_id": f"check-fact-{number}",
            "section": "facts",
            "statement_type": "fact",
            "text": fact["text"],
            "evidence_refs": fact["evidence_refs"],
        }
        for number, fact in enumerate(facts, start=1)
    ] + [
        {
            "claim_id": f"check-summary-{number}",
            "section": "summary",
            "statement_type": "fact",
            "text": sentence,
            "evidence_refs": [source.evidence_id for source in sources],
        }
        for number, sentence in enumerate(sentences, start=1)
    ]
    if not claims:
        return facts, summary
    evidence = {
        source.evidence_id: {"kind": "news", "text": source.text, "locator": {}}
        for source in by_evidence.values()
    }
    verdicts, used = verify_claims(claims, evidence, task=FACT_CHECK_TASK, system=FACT_CHECK_SYSTEM_PROMPT)
    usage.extend(used)
    kept_facts = []
    for number, fact in enumerate(facts, start=1):
        verdict = verdicts[f"check-fact-{number}"]
        if verdict["verdict"] == "supported":
            kept_facts.append({**fact, "claim_id": f"fact-{len(kept_facts) + 1}"})
        else:
            rejected.append({"text": fact["text"], "stage": "fact_check", **verdict})
    kept_sentences = []
    for number, sentence in enumerate(sentences, start=1):
        verdict = verdicts[f"check-summary-{number}"]
        if verdict["verdict"] == "supported":
            kept_sentences.append(sentence)
        else:
            rejected.append({"text": sentence, "stage": "summary_check", **verdict})
    return kept_facts, " ".join(kept_sentences)


def summarize_event(event: dict, diagnostics: dict | None = None) -> dict:
    payload = SummarizeEventInput.model_validate({"event": event}).event
    sources = sources_of(payload)
    if not sources:
        return GroundedSummaryResult.model_validate(
            {"summary": payload.title, "facts": [], "entities": [], "topics": topics_of(RawTopics(), "")}
        ).model_dump(mode="json")
    prompt = build_prompt(payload, sources)
    raw, facts, summary = RawSummary(), [], ""
    rejected: list[dict] = []
    usage: list[dict] = []
    for attempt in range(ATTEMPTS):
        result = call_llm(
            "summarize_event",
            LLMInput(system=SUMMARY_SYSTEM_PROMPT, user=prompt),
            MAX_TOKENS,
            response_model=RawSummary,
            temperature=RETRY_TEMPERATURE if attempt else 0.0,
        )
        raw = RawSummary.model_validate(result.data)
        conditions = [
            RawFact(text=text, quote=text, source=source.label)
            for source in sources
            for text in condition_sentences(source.text)
        ]
        # Conditions undergo the same checks; preserve them before MAX_FACTS.
        facts = verified_facts([*conditions, *raw.facts], sources, rejected)
        summary = summary_text(raw, facts, sources, payload.title)
        if facts or summary != payload.title:
            facts, checked = checked_facts_and_summary(facts, summary, sources, rejected, usage)
            summary = checked or (facts[0]["text"] if facts else payload.title)
        if facts:
            break
    if diagnostics is not None:
        diagnostics.update(rejected=rejected, usage=usage)
    return GroundedSummaryResult.model_validate(
        {
            "summary": summary or payload.title,
            "facts": facts,
            "entities": verified_entities(raw.entities, sources),
            "topics": topics_of(
                raw.topics, payload.title + " " + " ".join(source.text for source in sources)
            ),
        }
    ).model_dump(mode="json")

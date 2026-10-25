import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from pydantic import BeforeValidator, Field

from app.ai.insights.context import (
    CompanyFact,
    company_facts,
    evidence_id,
    flag_state,
    matched_features,
)
from app.ai.insights.prompts import INSIGHT_PROMPT_VERSION, INSIGHT_SYSTEM_PROMPT
from app.ai.providers import LLMInput, call_llm
from app.ai.schemas import BuildInsightInput, EventPayload, InsightEnvelope
from app.ai.summarization.conflicts import source_conflicts
from app.ai.summarization.grounding import normalize_text, shorten, unsupported_numbers
from app.ai.summarization.summarize import Lenient, StrList
from app.ai.validation import apply_validation, build_catalog
from app.integrations.ai import AIError

SECTIONS = ("bank_view", "ai_interpretation", "risks", "opportunities", "actions")
SECTION_PREFIX = {
    "bank_view": "bank",
    "ai_interpretation": "interpretation",
    "risks": "risk",
    "opportunities": "opportunity",
    "actions": "action",
}
MAX_FACTS = 6
MAX_CLAIMS = 3
MAX_BANK_FRAGMENTS = 4
MAX_CLAIM_CHARS = 600
MAX_UNKNOWN_CHARS = 220
MAX_UNKNOWNS = 8
MAX_TOKENS = 2800
RETRY_TEMPERATURE = 0.3
ATTEMPTS = 2
SEARCH_LIMIT = 5
LOAN_THEMES = {"ключевая ставка", "кредитование"}
LOAN_FLAG = "CL_PRODUCT_LOA_MARK"
DERIVED_SECTIONS = frozenset({"risks", "opportunities", "actions"})
LABEL_MENTION = re.compile(r"\s*[(\[]?\b[NCB]\d{1,2}\b(?:\s*[,;]\s*\b[NCB]\d{1,2}\b)*[)\]]?")


def to_claims(value):
    if value is None:
        return []
    if isinstance(value, dict | str):
        value = [value]
    return [item if isinstance(item, dict) else {"text": str(item)} for item in value if item is not None]


Claims = Annotated[list["RawClaim"], BeforeValidator(to_claims)]


class RawClaim(Lenient):
    text: str = ""
    evidence_ids: StrList = Field(default_factory=list)


class RawInsight(Lenient):
    bank_view: Claims = Field(default_factory=list)
    ai_interpretation: Claims = Field(default_factory=list)
    risks: Claims = Field(default_factory=list)
    opportunities: Claims = Field(default_factory=list)
    actions: Claims = Field(default_factory=list)
    unknowns: StrList = Field(default_factory=list)


def event_date(event) -> date:
    if event.published_at:
        try:
            return datetime.fromisoformat(event.published_at).date()
        except ValueError:
            pass
    return date.today()


def event_facts(event) -> list[dict]:
    known = {item.id for item in event.evidence if item.kind == "news"}
    facts = []
    for item in event.facts or []:
        refs = [ref for ref in item.get("evidence_refs", []) if ref in known]
        if item.get("text") and refs:
            facts.append(
                {"claim_id": f"fact-{len(facts) + 1}", "text": item["text"], "evidence_refs": refs[:2]}
            )
    if not facts and event.facts is None:
        for item in event.evidence:
            if item.kind == "news" and item.excerpt.strip():
                facts.append(
                    {
                        "claim_id": f"fact-{len(facts) + 1}",
                        "text": item.excerpt.strip()[:300],
                        "evidence_refs": [item.id],
                    }
                )
    return facts[:MAX_FACTS]


def search_queries(event) -> list[str]:
    queries = [event.title]
    topics = event.topics if isinstance(event.topics, dict) else {}
    themes = " ".join(topics.get("theme", [])[:3])
    if themes:
        queries.append(themes)
    return list(dict.fromkeys(query for query in queries if query.strip()))


def find_bank_fragments(tools, event) -> tuple[list[dict], list[dict]]:
    as_of = event_date(event).isoformat()
    seen: dict[str, dict] = {}
    steps = []
    for query in search_queries(event):
        found = tools.search_bank_analytics(query, as_of, SEARCH_LIMIT)
        items = found.get("items", [])
        steps.append(
            {
                "tool": "search_bank_analytics",
                "query": query,
                "as_of": as_of,
                "returned": [
                    {"chunk_id": item["chunk_id"], "page": item["page"], "score": item["score"]}
                    for item in items
                ],
                "empty_reason": found.get("empty_reason"),
            }
        )
        for item in items:
            seen.setdefault(item["chunk_id"], item)
    ranked = sorted(
        seen.values(), key=lambda item: (item["historical"], item["date_unknown"], -item["score"])
    )
    return ranked, steps


def bank_evidence(hit: dict) -> dict:
    digest = hashlib.sha1(hit["excerpt"].encode("utf-8")).hexdigest()[:12]
    return {
        "id": evidence_id("bank", hit["document_id"], hit["version"], str(hit["page"]), digest),
        "kind": "bank",
        "source_id": hit["document_id"],
        "version": hit["version"],
        "locator": {
            "page": hit["page"],
            **({"document_date": hit["document_date"]} if hit.get("document_date") else {}),
            **({"title": hit["title"]} if hit.get("title") else {}),
        },
        "excerpt": hit["excerpt"],
    }


def company_evidence(fact: CompanyFact, context: dict) -> dict:
    return {
        "id": fact.evidence_id,
        "kind": "company",
        "source_id": context["company_id"],
        "version": context["profile_version"],
        "locator": {"feature_path": f"features.{fact.feature}"},
        "excerpt": fact.excerpt,
    }


def aliases_for(facts: list[dict], company: list[CompanyFact], bank: list[dict]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for ref in dict.fromkeys(ref for claim in facts for ref in claim["evidence_refs"]):
        aliases[f"N{len(aliases) + 1}"] = ref
    for index, fact in enumerate(company, start=1):
        aliases[f"C{index}"] = fact.evidence_id
    for index, item in enumerate(bank, start=1):
        aliases[f"B{index}"] = item["id"]
    return aliases


def build_prompt(
    event,
    focus: dict,
    facts: list[dict],
    company: list[CompanyFact],
    bank: list[dict],
    matches,
    aliases: dict[str, str],
) -> str:
    by_id = {value: key for key, value in aliases.items()}
    news: dict[str, list[str]] = {}
    for claim in facts:
        news.setdefault(by_id[claim["evidence_refs"][0]], []).append(claim["text"])
    payload = {
        "event": {
            "title": event.title,
            "published_at": event.published_at,
            "topics": event.topics if isinstance(event.topics, dict) else {},
        },
        "news": [{"id": alias, "facts": texts} for alias, texts in news.items()],
        "user_focus": {"topics": focus.get("topics", []), "priorities": focus.get("priorities", [])},
        "company_features": [{"id": by_id[fact.evidence_id], "text": fact.excerpt} for fact in company],
        "matched_with_event": matches,
        "bank_fragments": [
            {
                "id": by_id[item["id"]],
                "document_date": item["document_date"],
                "date_unknown": item["date_unknown"],
                "text": item["excerpt"],
            }
            for item in bank
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def validated_claims(
    section: str,
    items: list[RawClaim],
    candidates: dict[str, dict],
    aliases: dict[str, str],
    premise_ids: set[str],
    number_source: str,
    dropped: list[dict],
    inherited: list[str] | None = None,
) -> list[dict]:
    claims, seen = [], set()
    for item in items:
        text = LABEL_MENTION.sub("", " ".join(item.text.split())).replace("  ", " ").strip()
        refs = [
            ref
            for ref in dict.fromkeys(aliases.get(raw, raw) for raw in item.evidence_ids)
            if ref in candidates
        ]
        if not item.evidence_ids and inherited and section in DERIVED_SECTIONS:
            refs = list(inherited)
        reason = None
        if section == "bank_view":
            refs = [ref for ref in refs if candidates[ref]["kind"] == "bank"]
        if not text or len(text) > MAX_CLAIM_CHARS:
            reason = "empty_or_too_long"
        elif not refs:
            reason = "no_valid_evidence"
        elif section == "ai_interpretation" and not (
            any(candidates[ref]["kind"] == "company" for ref in refs)
            and any(ref in premise_ids for ref in refs)
        ):
            reason = "missing_company_feature_or_premise"
        elif unsupported_numbers(text, number_source):
            reason = "number_not_in_sources"
        elif normalize_text(text) in seen:
            reason = "duplicate"
        if reason:
            dropped.append({"section": section, "reason": reason, "text": text[:200]})
            continue
        seen.add(normalize_text(text))
        claims.append(
            {
                "claim_id": f"{SECTION_PREFIX[section]}-{len(claims) + 1}",
                "text": text,
                "evidence_refs": refs,
            }
        )
        if len(claims) == MAX_CLAIMS:
            break
    return claims


def temporal_unknowns(hits: list[dict], limit: int = 2) -> list[str]:
    notes = []
    seen = set()
    for hit in hits:
        status = hit.get("temporal_status")
        key = (hit.get("document_id"), hit.get("version"))
        if not status or status == "current" or key in seen:
            continue
        seen.add(key)
        title = hit.get("title") or "без названия"
        stamp = f" от {hit['document_date']}" if hit.get("document_date") else " без даты"
        reason = hit.get("temporal_reason") or status
        notes.append(f"Материал банка «{title}»{stamp}: {reason}, позиция не показана как текущая")
        if len(notes) == limit:
            break
    return notes


def domain_unknowns(
    event, context: dict, bank_used: list[dict], bank_all: list[dict], has_bank_view: bool
) -> list[str]:
    unknowns = []
    topics = event.topics if isinstance(event.topics, dict) else {}
    if not has_bank_view:
        unknowns.append("Нет подтверждающих материалов банка на дату события")
    if bank_all and not bank_used:
        unknowns.append("Найдены только исторические материалы банка, текущая позиция банка не подтверждена")
    unknowns.extend(temporal_unknowns(bank_all))
    if any(item["date_unknown"] for item in bank_used):
        unknowns.append("Дата использованного материала банка неизвестна")
    concerns_loans = LOAN_FLAG in (topics.get("product") or []) or LOAN_THEMES & set(
        topics.get("theme") or []
    )
    if concerns_loans:
        state = flag_state(context, LOAN_FLAG)
        if state == "true":
            unknowns.append(
                "Сумма задолженности, тип ставки и условия кредитов неизвестны, в данных есть только наличие кредитного продукта"
            )
        elif state == "false":
            unknowns.append("Долг компании в других банках, его сумма и тип ставки неизвестны")
        else:
            unknowns.append(
                "Наличие кредитного продукта банка в профиле не подтверждено, долг компании, его сумма и тип ставки неизвестны"
            )
    return unknowns


@dataclass
class Prepared:
    context: dict
    payload: EventPayload
    focus: dict
    facts: list[dict]
    company: list[CompanyFact]
    matches: list[dict]
    company_ids: dict[str, dict]
    news_ids: set[str]


@dataclass
class Composed:
    sections: dict[str, list[dict]]
    raw_unknowns: list[str]
    dropped: list[dict]
    usage_steps: list[dict]
    bank: list[dict]
    hits: list[dict]


def prepare_insight(company_context: dict, user_focus: dict, event: dict, tools) -> Prepared:
    request = BuildInsightInput.model_validate(
        {"company_context": company_context, "user_focus": user_focus, "event": event}
    )
    context, payload = request.company_context.model_dump(mode="json"), request.event
    if tools.get_company_context()["company_id"] != context["company_id"]:
        raise AIError("forbidden", "Инструмент ограничен выбранной компанией")
    facts = event_facts(payload)
    company = company_facts(context)
    topics = payload.topics if isinstance(payload.topics, dict) else {}
    return Prepared(
        context=context,
        payload=payload,
        focus=user_focus,
        facts=facts,
        company=company,
        matches=matched_features(context, topics),
        company_ids={fact.evidence_id: company_evidence(fact, context) for fact in company},
        news_ids={ref for claim in facts for ref in claim["evidence_refs"]},
    )


def select_bank(hits: list[dict]) -> list[dict]:
    usable = [hit for hit in hits if not hit["historical"]][:MAX_BANK_FRAGMENTS]
    return [{**hit, **bank_evidence(hit)} for hit in usable]


def compose_card(prepared: Prepared, hits: list[dict]) -> Composed:
    bank = select_bank(hits)
    bank_ids = {item["id"]: item for item in bank}
    aliases = aliases_for(prepared.facts, prepared.company, bank)
    candidates = {
        **{ref: {"kind": "news"} for ref in prepared.news_ids},
        **{ref: {"kind": "company"} for ref in prepared.company_ids},
        **{ref: {"kind": "bank"} for ref in bank_ids},
    }
    payload = prepared.payload
    number_source = " ".join(
        [payload.title, payload.summary or ""]
        + [claim["text"] for claim in prepared.facts]
        + [fact.excerpt + " " + fact.value for fact in prepared.company]
        + [item["excerpt"] for item in bank]
    )
    raw, dropped, usage_steps = RawInsight(), [], []
    sections: dict[str, list[dict]] = {section: [] for section in SECTIONS}
    if prepared.facts:
        prompt = build_prompt(
            payload, prepared.focus, prepared.facts, prepared.company, bank, prepared.matches, aliases
        )
        for attempt in range(ATTEMPTS):
            dropped.clear()
            result = call_llm(
                "build_insight",
                LLMInput(system=INSIGHT_SYSTEM_PROMPT, user=prompt),
                MAX_TOKENS,
                response_model=RawInsight,
                temperature=RETRY_TEMPERATURE if attempt else 0.0,
            )
            usage_steps.append(
                {
                    "llm": "build_insight",
                    "attempt": attempt + 1,
                    "request_id": result.request_id,
                    "model": result.model_id,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "cost_rub": result.usage.cost_rub,
                }
            )
            raw = RawInsight.model_validate(result.data)
            sections = {}
            for section in SECTIONS:
                inherited = list(
                    dict.fromkeys(
                        ref
                        for claim in sections.get("ai_interpretation", [])
                        for ref in claim["evidence_refs"]
                    )
                )
                sections[section] = validated_claims(
                    section,
                    getattr(raw, section),
                    candidates,
                    aliases,
                    prepared.news_ids | set(bank_ids),
                    number_source,
                    dropped,
                    inherited,
                )
            if sections["ai_interpretation"]:
                break
    return Composed(sections, raw.unknowns, dropped, usage_steps, bank, hits)


def base_steps(prepared: Prepared) -> list[dict]:
    return [
        {
            "tool": "get_company_context",
            "company_id": prepared.context["company_id"],
            "profile_version": prepared.context["profile_version"],
        },
        {
            "tool": "get_event",
            "event_id": prepared.payload.id,
            "event_version": prepared.payload.version,
            "facts": len(prepared.facts),
        },
    ]


def profile_excerpts(context: dict) -> dict[str, str]:
    return {fact.feature: fact.excerpt for fact in company_facts(context)}


def assemble_envelope(
    prepared: Prepared,
    composed: Composed,
    steps: list[dict],
    plan: list[str],
    stop_reason: str,
    extra_unknowns: list[str] | None = None,
    extra_trace: dict | None = None,
    drop_bank_view: bool = False,
) -> dict:
    sections = dict(composed.sections)
    if drop_bank_view:
        sections["bank_view"] = []
    bank_ids = {item["id"]: item for item in composed.bank}
    bank_view = sections["bank_view"] or None
    used_bank = [bank_ids[ref] for claim in sections["bank_view"] for ref in claim["evidence_refs"]]
    unknowns = domain_unknowns(
        prepared.payload, prepared.context, used_bank, composed.hits, bank_view is not None
    )
    if not prepared.facts:
        unknowns.insert(0, "Источников недостаточно для вывода о влиянии события на компанию")
    conflicts = source_conflicts(prepared.facts)
    unknowns[:0] = conflicts
    for text in [*(extra_unknowns or []), *composed.raw_unknowns]:
        cleaned = shorten(LABEL_MENTION.sub("", text).strip(), MAX_UNKNOWN_CHARS)
        if cleaned and cleaned not in unknowns:
            unknowns.append(cleaned)
    unknowns = unknowns[:MAX_UNKNOWNS]
    claims = prepared.facts + [claim for section in SECTIONS for claim in sections[section]]
    refs = list(dict.fromkeys(ref for claim in claims for ref in claim["evidence_refs"]))
    evidence = [bank_ids[ref] for ref in refs if ref in bank_ids] + [
        prepared.company_ids[ref] for ref in refs if ref in prepared.company_ids
    ]
    evidence = [
        {key: item[key] for key in ("id", "kind", "source_id", "version", "locator", "excerpt")}
        for item in evidence
    ]
    trace = {
        "prompt_version": INSIGHT_PROMPT_VERSION,
        "plan": plan,
        "steps": steps,
        "company_features_offered": [fact.feature for fact in prepared.company],
        "matched_with_event": prepared.matches,
        "bank_fragments_offered": [item["id"] for item in composed.bank],
        "dropped_claims": composed.dropped,
        "source_conflicts": conflicts,
        "stop_reason": stop_reason,
        **(extra_trace or {}),
    }
    result = {
        "facts": prepared.facts,
        "bank_view": bank_view,
        "ai_interpretation": sections["ai_interpretation"],
        "risks": sections["risks"],
        "opportunities": sections["opportunities"],
        "actions": sections["actions"],
        "unknowns": unknowns,
        "evidence_refs": refs,
        "trace_id": str(uuid.uuid4()),
    }
    catalog = build_catalog(
        prepared.context,
        prepared.payload,
        prepared.facts,
        composed.hits,
        profile_excerpts(prepared.context),
    )
    checked, report = apply_validation({"result": result, "evidence": evidence}, catalog)
    trace["validation"] = report
    return InsightEnvelope.model_validate({**checked, "trace": trace}).model_dump(mode="json")


FIXED_PLAN = [
    "read_event_facts",
    "read_company_features",
    "search_bank_analytics",
    "compose_insight",
    "check_grounding",
]


def build_insight(company_context: dict, user_focus: dict, event: dict, tools) -> dict:
    prepared = prepare_insight(company_context, user_focus, event, tools)
    hits, search_steps = find_bank_fragments(tools, prepared.payload)
    composed = compose_card(prepared, hits)
    steps = [*base_steps(prepared), *search_steps, *composed.usage_steps]
    return assemble_envelope(
        prepared, composed, steps, FIXED_PLAN, "completed" if prepared.facts else "no_event_facts"
    )

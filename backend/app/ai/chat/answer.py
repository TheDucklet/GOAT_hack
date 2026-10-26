import json
import re
import uuid

from pydantic import Field

from app.ai.chat.guard import split_question
from app.ai.chat.missing import missing_parameters
from app.ai.chat.prompts import ANSWER_SYSTEM_PROMPT, CHAT_PROMPT_VERSION, ROUTER_SYSTEM_PROMPT
from app.ai.insights.build import (
    LABEL_MENTION,
    SEARCH_LIMIT,
    Prepared,
    aliases_for,
    event_date,
    prepare_insight,
    profile_excerpts,
    select_bank,
    temporal_unknowns,
)
from app.ai.insights.context import mechanism_bases
from app.ai.providers import LLMError, LLMInput, call_llm
from app.ai.schemas import AnswerChatInput, ChatEnvelope
from app.ai.summarization.conditions import condition_context
from app.ai.summarization.conflicts import source_conflicts
from app.ai.summarization.grounding import normalize_text, shorten, strip_instructions, supported_sentences
from app.ai.summarization.summarize import Lenient, StrList
from app.ai.validation import build_catalog, validate_answer
from app.integrations.ai import AIError
from app.publication_policy import NO_SOURCES_TEXT, REFUSAL_TEXT

FATAL_CODES = frozenset({"budget_exhausted", "model_not_allowed", "ai_unavailable"})
HISTORY_TURNS = 6
HISTORY_CHARS = 700
MAX_ANSWER_CHARS = 1800
MAX_UNKNOWN_CHARS = 220
MAX_UNKNOWNS = 8
MAX_TOKENS = 1500
RETRY_TEMPERATURE = 0.3
SEARCH_INTENTS = frozenset({"bank_position", "importance"})
INTENTS = frozenset({"importance", "missing_data", "bank_position", "details", "other"})
CONFLICT_MENTION = re.compile(r"расходя|расхожд|различ|противореч|по-разному|не совпада", re.IGNORECASE)
CONFLICT_SENTENCE = "Источники события расходятся в данных, поэтому итоговая цифра не установлена."
NO_SOURCES_UNKNOWN = "Нет источников, подтверждающих ответ на этот вопрос"
REFUSED_UNKNOWN = "Запрос выходит за пределы выбранной компании и инструментов, он не выполнен"
MISSING_KEYWORDS = (
    "не хватает",
    "недостаёт",
    "недостает",
    "каких данных",
    "какие данные",
    "для расчёт",
    "для расчет",
)
BANK_KEYWORDS = ("банк", "позици", "аналитик")
MISSING_CONDITION = re.compile(r"^(?:неизвестн\w*|недостат\w*|нет\s+(?:данных|сведений))\b", re.IGNORECASE)
VAGUE_EFFECT = re.compile(r"\bзначительн\w*\s+или\s+незначительн\w*\b", re.IGNORECASE)


class RawRoute(Lenient):
    intent: str = "other"
    search_query: str | None = None


class RawMechanism(Lenient):
    condition: str = ""
    consequence: str = ""
    evidence_ids: StrList = Field(default_factory=list)


class RawAnswer(Lenient):
    answer: str = ""
    evidence_ids: StrList = Field(default_factory=list)
    unknowns: StrList = Field(default_factory=list)
    mechanism: RawMechanism | None = None


def usage_step(label: str, result) -> dict:
    return {
        "llm": label,
        "request_id": result.request_id,
        "model": result.model_id,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cost_rub": result.usage.cost_rub,
    }


def keyword_intent(question: str) -> str:
    lowered = question.lower()
    if any(word in lowered for word in MISSING_KEYWORDS):
        return "missing_data"
    if any(word in lowered for word in BANK_KEYWORDS):
        return "bank_position"
    if "почему" in lowered or "важн" in lowered:
        return "importance"
    return "other"


def route_question(
    question: str, history: list[dict], prepared: Prepared
) -> tuple[str, str | None, list[dict]]:
    payload = {
        "question": question,
        "history": history,
        "event_title": prepared.payload.title,
    }
    try:
        result = call_llm(
            "chat_router",
            LLMInput(system=ROUTER_SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False)),
            300,
            response_model=RawRoute,
            temperature=0.0,
        )
    except LLMError as error:
        if error.code in FATAL_CODES:
            raise
        return keyword_intent(question), None, []
    route = RawRoute.model_validate(result.data)
    intent = route.intent if route.intent in INTENTS else keyword_intent(question)
    query = " ".join((route.search_query or "").split())[:120] or None
    return intent, query, [usage_step("chat_router", result)]


def previous_turns(history: list[dict]) -> list[dict]:
    return [
        {"role": item["role"], "text": item["text"][:HISTORY_CHARS]} for item in history[:-1][-HISTORY_TURNS:]
    ]


def build_prompt(
    prepared: Prepared,
    question: str,
    turns: list[dict],
    bank: list[dict],
    aliases: dict,
    missing: list[str],
    intent: str = "other",
) -> str:
    by_id = {value: key for key, value in aliases.items()}
    news: dict[str, list[str]] = {}
    for claim in prepared.facts:
        news.setdefault(by_id[claim["evidence_refs"][0]], []).append(claim["text"])
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    payload = {
        "response_mode": "business" if intent in {"importance", "missing_data"} else "factual",
        "question": question,
        "history": turns,
        "event": {
            "title": prepared.payload.title,
            "published_at": prepared.payload.published_at,
            "topics": topics,
        },
        "news": [{"id": alias, "facts": texts} for alias, texts in news.items()],
        "user_focus": {
            "topics": prepared.focus.get("topics", []),
            "priorities": prepared.focus.get("priorities", []),
        },
        "company_features": [
            {"id": by_id[fact.evidence_id], "text": fact.excerpt} for fact in prepared.company
        ],
        "matched_with_event": prepared.matches,
        "mechanism_bases": mechanism_bases(prepared.company, aliases),
        "source_conditions": condition_context(prepared.payload, aliases),
        "bank_fragments": [
            {"id": by_id[item["id"]], "document_date": item["document_date"], "text": item["excerpt"]}
            for item in bank
        ],
        "known_missing_parameters": missing,
    }
    return json.dumps(payload, ensure_ascii=False)


def repair_prompt(prompt: str, raw: RawAnswer, reason: str, validation: dict) -> str:
    payload = json.loads(prompt)
    payload["validation_feedback"] = {
        "reason": reason,
        "problems": validation.get("reasons", []),
        "rejected_answer": raw.answer[:MAX_ANSWER_CHARS],
        "rejected_mechanism": raw.mechanism.model_dump() if raw.mechanism is not None else None,
    }
    return json.dumps(payload, ensure_ascii=False)


def clean_answer(
    raw: RawAnswer, candidates: dict[str, dict], aliases: dict[str, str], number_source: str
) -> tuple[str, list[str], str | None]:
    answer, evidence_ids = raw.answer, raw.evidence_ids
    if raw.mechanism is not None:
        condition = " ".join(raw.mechanism.condition.split()).strip(" .")
        consequence = " ".join(raw.mechanism.consequence.split()).strip(" .")
        if not condition or not consequence:
            return "", [], "incomplete_conditional_mechanism"
        if MISSING_CONDITION.search(condition):
            return "", [], "missing_applicability_condition"
        if VAGUE_EFFECT.search(consequence):
            return "", [], "non_specific_consequence"
        if not re.search(r"\b(?:может|могут)\b", consequence, re.IGNORECASE):
            return "", [], "unqualified_conditional_consequence"
        answer = f"Если {condition}, то {consequence}."
        evidence_ids = raw.mechanism.evidence_ids
    text = LABEL_MENTION.sub("", " ".join(answer.split())).replace("  ", " ").strip()[:MAX_ANSWER_CHARS]
    refs = [
        ref for ref in dict.fromkeys(aliases.get(item, item) for item in evidence_ids) if ref in candidates
    ]
    supported = supported_sentences(text, number_source) if text else ""
    reason = None
    if not text:
        reason = "empty_answer"
    elif not supported:
        reason = "numbers_not_in_sources"
    elif not refs:
        reason = "no_valid_evidence"
    return supported, refs, reason


def refusal(prepared: Prepared, removed: list[str], steps: list[dict]) -> dict:
    result = {
        "answer": REFUSAL_TEXT,
        "evidence_refs": [],
        "unknowns": [REFUSED_UNKNOWN],
        "trace_id": str(uuid.uuid4()),
        "usage": usage_total(steps),
    }
    trace = {
        "prompt_version": CHAT_PROMPT_VERSION,
        "intent": "refused",
        "steps": steps,
        "refused_fragments": removed,
        "stop_reason": "refused",
    }
    return ChatEnvelope.model_validate({"result": result, "evidence": [], "trace": trace}).model_dump(
        mode="json"
    )


def usage_total(steps: list[dict]) -> dict:
    llm = [step for step in steps if "llm" in step]
    return {
        "llm_calls": len(llm),
        "input_tokens": sum(step["input_tokens"] for step in llm),
        "output_tokens": sum(step["output_tokens"] for step in llm),
        "cost_rub": round(sum(step["cost_rub"] for step in llm), 6),
        "models": sorted({step["model"] for step in llm}),
    }


def evidence_for(refs: list[str], bank_ids: dict[str, dict], prepared: Prepared) -> list[dict]:
    items = (
        [
            item.model_dump(mode="json")
            for item in prepared.payload.evidence
            if item.kind == "news" and item.id in refs
        ]
        + [bank_ids[ref] for ref in refs if ref in bank_ids]
        + [prepared.company_ids[ref] for ref in refs if ref in prepared.company_ids]
    )
    return [
        {key: item[key] for key in ("id", "kind", "source_id", "version", "locator", "excerpt")}
        for item in items
    ]


def numeric_support(prepared: Prepared, bank: list[dict]) -> str:
    return " ".join(
        [prepared.payload.title, prepared.payload.summary or "", prepared.payload.published_at or ""]
        + [claim["text"] for claim in prepared.facts]
        + [strip_instructions(publication.text) for publication in prepared.payload.publications]
        + [fact.excerpt + " " + fact.value for fact in prepared.company]
        + [item["excerpt"] for item in bank]
    )


def answer_chat(
    company_context: dict,
    user_focus: dict,
    event: dict,
    history: list[dict],
    tools,
    publication_feedback: list[dict] | None = None,
) -> dict:
    request = AnswerChatInput.model_validate(
        {"company_context": company_context, "user_focus": user_focus, "event": event, "history": history}
    )
    turns_all = [item.model_dump() for item in request.history]
    if turns_all[-1]["role"] != "user":
        raise AIError("ai_contract_error", "Последнее сообщение диалога должно быть вопросом пользователя")
    prepared = prepare_insight(company_context, user_focus, event, tools)
    company_id = prepared.context["company_id"]
    steps = [
        {
            "tool": "get_company_context",
            "company_id": company_id,
            "profile_version": prepared.context["profile_version"],
        },
        {"tool": "get_event", "event_id": prepared.payload.id, "event_version": prepared.payload.version},
    ]
    question, removed = split_question(turns_all[-1]["text"], company_id)
    if not question:
        return refusal(prepared, removed, steps)
    turns = previous_turns(turns_all)
    intent, query, route_usage = route_question(question, turns, prepared)
    steps.extend(route_usage)
    hits: list[dict] = []
    if query or intent in SEARCH_INTENTS:
        query = query or prepared.payload.title
        as_of = event_date(prepared.payload).isoformat()
        found = tools.search_bank_analytics(query, as_of, SEARCH_LIMIT)
        hits = found.get("items", [])
        steps.append(
            {
                "tool": "search_bank_analytics",
                "query": query,
                "as_of": as_of,
                "returned": [
                    {"chunk_id": item["chunk_id"], "page": item["page"], "historical": item["historical"]}
                    for item in hits
                ],
                "empty_reason": found.get("empty_reason"),
            }
        )
    bank = select_bank(hits)
    bank_ids = {item["id"]: item for item in bank}
    aliases = aliases_for(prepared.facts, prepared.company, bank)
    candidates = {
        **{ref: {"kind": "news"} for ref in prepared.news_ids},
        **{ref: {"kind": "company"} for ref in prepared.company_ids},
        **{ref: {"kind": "bank"} for ref in bank_ids},
    }
    missing = missing_parameters(prepared)
    number_source = numeric_support(prepared, bank)
    catalog = build_catalog(
        prepared.context,
        prepared.payload,
        prepared.facts,
        hits,
        profile_excerpts(prepared.context),
    )
    prompt = build_prompt(prepared, question, turns, bank, aliases, missing, intent)
    if publication_feedback:
        inputs = json.loads(prompt)
        inputs["publication_feedback"] = publication_feedback
        prompt = json.dumps(inputs, ensure_ascii=False)
    answer, refs, reason, raw = "", [], "not_started", RawAnswer()
    validation: dict = {}
    validation_attempts: list[dict] = []
    for attempt in range(2):
        result = call_llm(
            "answer_chat",
            LLMInput(system=ANSWER_SYSTEM_PROMPT, user=prompt),
            MAX_TOKENS,
            response_model=RawAnswer,
            temperature=RETRY_TEMPERATURE if attempt else 0.0,
        )
        steps.append({**usage_step("answer_chat", result), "attempt": attempt + 1})
        raw = RawAnswer.model_validate(result.data)
        answer, refs, reason = clean_answer(raw, candidates, aliases, number_source)
        validation = {}
        if reason is None:
            checked = validate_answer(
                answer, refs, evidence_for(refs, bank_ids, prepared), catalog, number_source
            )
            validation = checked["record"]
            if checked["verdict"] != "supported":
                reason = "validation_failed"
        validation_attempts.append(
            {
                "attempt": attempt + 1,
                "reason": reason,
                "record": validation or None,
                "candidate_answer": answer,
                "candidate_refs": refs,
            }
        )
        if reason is None:
            break
        prompt = repair_prompt(prompt, raw, reason, validation)
    unknowns: list[str] = []
    conflicts = source_conflicts(prepared.facts)
    if reason is not None:
        answer, refs = NO_SOURCES_TEXT, []
        unknowns.append(NO_SOURCES_UNKNOWN)
        codes = sorted({item["code"] for item in validation.get("reasons", [])}) if validation else []
        if codes:
            unknowns.append(f"Ответ не прошёл проверку оснований ({', '.join(codes)})")
    elif conflicts and not CONFLICT_MENTION.search(answer):
        answer = f"{answer} {CONFLICT_SENTENCE}"
    unknowns.extend(conflicts)
    unknowns.extend(temporal_unknowns(hits))
    if removed:
        answer = f"{answer} {REFUSAL_TEXT}"
        unknowns.append(REFUSED_UNKNOWN)
    if intent == "missing_data":
        unknowns.extend(missing)
    unknowns.extend(
        shorten(LABEL_MENTION.sub("", text).strip(), MAX_UNKNOWN_CHARS)
        for text in raw.unknowns
        if text.strip()
    )
    unknowns = list(dict.fromkeys(item for item in unknowns if normalize_text(item)))[:MAX_UNKNOWNS]
    if not refs and not unknowns:
        unknowns = [NO_SOURCES_UNKNOWN]
    evidence = evidence_for(refs, bank_ids, prepared)
    steps.append(
        {"stop": "answered" if reason is None else "no_sources", "intent": intent, "evidence_ids": refs}
    )
    trace = {
        "prompt_version": CHAT_PROMPT_VERSION,
        "intent": intent,
        "question": question,
        "history_turns": len(turns),
        "steps": steps,
        "refused_fragments": removed,
        "bank_fragments_offered": [item["id"] for item in bank],
        "company_features_offered": [fact.feature for fact in prepared.company],
        "stop_reason": "answered" if reason is None else "no_sources",
        "source_conflicts": conflicts,
        "validation": validation or None,
        "validation_attempts": validation_attempts,
    }
    result_body = {
        "answer": answer,
        "evidence_refs": refs,
        "unknowns": unknowns,
        "trace_id": str(uuid.uuid4()),
        "usage": usage_total(steps),
    }
    return ChatEnvelope.model_validate(
        {"result": result_body, "evidence": evidence, "trace": trace}
    ).model_dump(mode="json")

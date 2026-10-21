import json
from dataclasses import dataclass, field

from pydantic import Field

from app.ai.agent.prompts import PLAN_SYSTEM_PROMPT, QUERY_SYSTEM_PROMPT, VERIFY_SYSTEM_PROMPT
from app.ai.insights.build import Composed, Prepared, bank_evidence, search_queries
from app.ai.providers import LLMError, LLMInput, call_llm
from app.ai.rag.search import query_terms, stem
from app.ai.summarization.summarize import Lenient, StrList

FATAL_CODES = frozenset({"budget_exhausted", "model_not_allowed", "ai_unavailable"})
MAX_QUERY_CHARS = 120
MAX_PLAN_QUERIES = 2
MAX_NEEDS = 5
BANK_REASONS = frozenset(
    {"no_bank_evidence", "only_historical", "fragments_not_relevant", "bank_claims_rejected"}
)


class RawPlan(Lenient):
    needs: StrList = Field(default_factory=list)
    queries: StrList = Field(default_factory=list)


class RawQuery(Lenient):
    query: str = ""
    reason: str = ""


class RawVerdict(Lenient):
    claim: int = 0
    verdict: str = ""
    reason: str = ""


class RawVerdicts(Lenient):
    verdicts: list[RawVerdict] = Field(default_factory=list)


@dataclass
class CheckResult:
    status: str
    reasons: list[dict] = field(default_factory=list)

    @property
    def searchable(self) -> bool:
        return any(item["code"] in BANK_REASONS for item in self.reasons)


def signature(query: str) -> frozenset[str]:
    return frozenset(stem(term) for term in query_terms(query))


def usage_step(label: str, result) -> dict:
    return {
        "llm": label,
        "request_id": result.request_id,
        "model": result.model_id,
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
        "cost_rub": result.usage.cost_rub,
    }


def clean_queries(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = " ".join(value.split())[:MAX_QUERY_CHARS]
        if len(query_terms(text)) >= 1 and signature(text) not in [signature(item) for item in cleaned]:
            cleaned.append(text)
    return cleaned


def make_plan(prepared: Prepared) -> tuple[list[str], list[str], list[dict]]:
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    context = {
        "event": {"title": prepared.payload.title, "themes": topics.get("theme", [])},
        "facts": [claim["text"] for claim in prepared.facts],
        "company": [fact.excerpt for fact in prepared.company[:10]],
        "matched_with_event": prepared.matches,
    }
    fallback = search_queries(prepared.payload)
    try:
        result = call_llm(
            "agent_plan",
            LLMInput(system=PLAN_SYSTEM_PROMPT, user=json.dumps(context, ensure_ascii=False)),
            700,
            response_model=RawPlan,
            temperature=0.0,
        )
    except LLMError as error:
        if error.code in FATAL_CODES:
            raise
        return (
            ["read_event_facts", "read_company_features", "search_bank_analytics", "compose_insight"],
            fallback,
            [],
        )
    plan = RawPlan.model_validate(result.data)
    needs = [" ".join(item.split())[:160] for item in plan.needs if item.strip()][:MAX_NEEDS]
    queries = clean_queries(plan.queries)[:MAX_PLAN_QUERIES] or fallback
    return (
        needs or ["read_event_facts", "read_company_features", "search_bank_analytics"],
        queries,
        [usage_step("agent_plan", result)],
    )


def verify_bank_claims(prepared: Prepared, composed: Composed) -> tuple[Composed, list[dict], list[dict]]:
    claims = composed.sections["bank_view"]
    if not claims:
        return composed, [], []
    by_id = {item["id"]: item for item in composed.bank}
    payload = {
        "event_facts": [claim["text"] for claim in prepared.facts],
        "claims": [
            {
                "claim": number,
                "text": claim["text"],
                "fragments": [by_id[ref]["excerpt"] for ref in claim["evidence_refs"] if ref in by_id],
            }
            for number, claim in enumerate(claims, start=1)
        ],
    }
    try:
        result = call_llm(
            "agent_check",
            LLMInput(system=VERIFY_SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False)),
            900,
            response_model=RawVerdicts,
            temperature=0.0,
        )
    except LLMError as error:
        if error.code in FATAL_CODES:
            raise
        return composed, [], []
    verdicts = {item.claim: item for item in RawVerdicts.model_validate(result.data).verdicts}
    kept, rejected = [], []
    for number, claim in enumerate(claims, start=1):
        verdict = verdicts.get(number)
        if verdict and verdict.verdict in {"insufficient", "contradiction"}:
            rejected.append(
                {"claim_id": claim["claim_id"], "verdict": verdict.verdict, "reason": verdict.reason[:200]}
            )
        else:
            kept.append(claim)
    sections = {**composed.sections, "bank_view": kept}
    updated = Composed(
        sections, composed.raw_unknowns, composed.dropped, composed.usage_steps, composed.bank, composed.hits
    )
    return updated, rejected, [usage_step("agent_check", result)]


def check_card(prepared: Prepared, composed: Composed, rejected: list[dict]) -> CheckResult:
    reasons: list[dict] = []
    if not prepared.facts:
        reasons.append({"code": "no_event_facts", "detail": "в событии нет проверенных фактов"})
    elif not composed.sections["ai_interpretation"]:
        reasons.append(
            {"code": "no_interpretation", "detail": "нет объяснения, подтверждённого признаками компании"}
        )
    if rejected:
        kinds = sorted({item["verdict"] for item in rejected})
        reasons.append(
            {
                "code": "bank_claims_rejected",
                "detail": "проверка не подтвердила утверждения банка: " + ", ".join(kinds),
            }
        )
    elif not composed.sections["bank_view"]:
        if composed.bank:
            reasons.append(
                {
                    "code": "fragments_not_relevant",
                    "detail": "найденные фрагменты не дали утверждений о позиции банка",
                }
            )
        elif composed.hits:
            reasons.append(
                {"code": "only_historical", "detail": "найдены только исторические материалы банка"}
            )
        else:
            reasons.append({"code": "no_bank_evidence", "detail": "материалы банка по запросам не найдены"})
    if any(item["verdict"] == "contradiction" for item in rejected):
        return CheckResult("contradiction", reasons)
    return CheckResult("insufficient" if reasons else "supported", reasons)


def fallback_queries(prepared: Prepared) -> list[str]:
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    themes = topics.get("theme", [])
    title_terms = query_terms(prepared.payload.title)
    industry = next(
        (item["value"] for item in prepared.matches if item["factor"] == "industry"),
        prepared.context["features"].get("MAINOKVED_NAME", {}).get("value", ""),
    )
    candidates = [
        " ".join(themes[:2]),
        " ".join(themes[:1] + title_terms[:2]),
        " ".join(title_terms[:3]),
        " ".join(query_terms(industry)[:3]),
        " ".join(themes[1:3]),
    ]
    return [item for item in candidates if item.strip()]


def next_query(
    prepared: Prepared, tried: list[str], check: CheckResult, outcomes: list[dict]
) -> tuple[str, str, list[dict]]:
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    context = {
        "event": {"title": prepared.payload.title, "themes": topics.get("theme", [])},
        "facts": [claim["text"] for claim in prepared.facts],
        "company_industry": prepared.context["features"].get("MAINOKVED_NAME", {}).get("value", ""),
        "previous_queries": outcomes,
        "problems": [item["detail"] for item in check.reasons],
    }
    seen = [signature(item) for item in tried]
    try:
        result = call_llm(
            "agent_query",
            LLMInput(system=QUERY_SYSTEM_PROMPT, user=json.dumps(context, ensure_ascii=False)),
            400,
            response_model=RawQuery,
            temperature=0.3,
        )
    except LLMError as error:
        if error.code in FATAL_CODES:
            raise
        result = None
    if result is not None:
        raw = RawQuery.model_validate(result.data)
        query = " ".join(raw.query.split())[:MAX_QUERY_CHARS]
        if query_terms(query) and signature(query) not in seen:
            return query, " ".join(raw.reason.split())[:240], [usage_step("agent_query", result)]
    for candidate in fallback_queries(prepared):
        if signature(candidate) not in seen:
            return (
                candidate,
                "запасной запрос из других терминов события и отрасли",
                [] if result is None else [usage_step("agent_query", result)],
            )
    return "", "новых запросов нет", [] if result is None else [usage_step("agent_query", result)]


def bank_ids_of(hits: list[dict]) -> list[str]:
    return [bank_evidence(hit)["id"] for hit in hits]

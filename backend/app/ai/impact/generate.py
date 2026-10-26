import json
import re
from datetime import date, datetime, timedelta, timezone

from app.ai.agent.runner import AgentOutcome, run_agent_detailed
from app.ai.agent.steps import FATAL_CODES, usage_step
from app.ai.chat.missing import missing_parameters
from app.ai.impact.assemble import (
    bank_context,
    next_actions,
    policy_fields,
    relevance_window,
    split_bank_view,
    statement,
    typed_sections,
)
from app.ai.impact.dates import grounded_date
from app.ai.impact.models import RawImpact, RawStatement
from app.ai.impact.prompts import IMPACT_PROMPT_VERSION, IMPACT_SYSTEM_PROMPT
from app.ai.impact.rubric import RUBRIC_VERSION, assess
from app.ai.insights.build import (
    LABEL_MENTION,
    MAX_UNKNOWN_CHARS,
    aliases_for,
    event_date,
    profile_excerpts,
)
from app.ai.insights.context import mechanism_bases
from app.ai.providers import LLMError, LLMInput, call_llm
from app.ai.schemas import InsightEnvelopeV2
from app.ai.summarization.conditions import condition_context
from app.ai.summarization.grounding import shorten, unsupported_numbers
from app.ai.validation import SUPPORTED, build_catalog
from app.ai.validation.checks import check_claim
from app.insight_versions import contract_versions

IMPACT_TOKENS = 1600
MAX_MECHANISM = 3
MAX_ASSUMPTIONS = 3
MAX_TEXT_CHARS = 600
MAX_SUMMARY_CHARS = 300
MAX_LABEL_CHARS = 120
MAX_UNKNOWNS = 12
MSK = timezone(timedelta(hours=3))
RELATIONSHIP_UNKNOWN = (
    "В данных есть связи компании (группа, общие физлица, платежи), но их смысл (поставка, кредит, владение) "
    "не установлен, в выводе они не использованы"
)
UNDATED_BANK_UNKNOWN = "Дата материала банка неизвестна, такая позиция не показана как текущая"
CAP_REASONS = {
    "no_exposure_evidence": "нет подтверждённого признака компании, связанного с событием",
    "medium_without_direct_link": "событие не названо прямо в отрасли, продуктах или географии компании",
    "high_without_direct_link": "событие не названо прямо в отрасли, продуктах или географии компании",
    "low_contradicts_direct_link": "связь события с компанией прямая, а малая сила не доказана данными",
    "single_factor": "подтверждён один независимый фактор",
    "exposure_not_quantified": "масштаб экспозиции не подтверждён числами с единицей и периодом",
    "trigger_not_dated": "срок триггера в источниках не назван",
}


def today_msk(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(MSK).date()


FIELD_MENTION = re.compile(
    r"\s*\((?:[^()]*(?:user_focus|company_features|bank_fragments|matched_with_event|profile_gaps)[^()]*)\)"
)
NON_IMPACT_FEATURES = frozenset({"CL_TYPE"})


def clean_text(text: str) -> str:
    flat = FIELD_MENTION.sub("", " ".join(text.split()))
    return LABEL_MENTION.sub("", flat).replace("  ", " ").strip()


def resolve_refs(raw: RawStatement, aliases: dict[str, str], candidates: dict[str, dict]) -> list[str]:
    return [
        ref
        for ref in dict.fromkeys(aliases.get(item, item) for item in raw.evidence_ids)
        if ref in candidates
    ]


class Verifier:
    def __init__(self, prepared, composed, evidence: dict[str, dict], candidates: dict[str, dict]):
        self.catalog = build_catalog(
            prepared.context,
            prepared.payload,
            prepared.facts,
            composed.hits,
            profile_excerpts(prepared.context),
        )
        self.evidence = {**self.catalog.news, **evidence}
        self.candidates = candidates
        self.support = " ".join(item["excerpt"] for item in evidence.values())
        self.dropped: list[dict] = []

    def accept_many(
        self, prefix: str, items: list[RawStatement], aliases: dict[str, str], kind: str, section: str
    ):
        accepted = []
        for index, item in enumerate(items, start=1):
            result = self.accept(f"{prefix}-{index}", item, aliases, kind, section)
            if result:
                accepted.append(result)
        return accepted

    def accept(
        self, claim_id: str, raw: RawStatement | None, aliases: dict[str, str], kind: str, section: str
    ):
        if raw is None:
            return None
        text = shorten(clean_text(raw.text), MAX_TEXT_CHARS)
        refs = resolve_refs(raw, aliases, self.candidates)
        if not text:
            return None
        claim = {"claim_id": claim_id, "text": text, "evidence_refs": refs}
        verdict, problems, valid, _ = check_claim(claim, section, self.evidence, self.catalog, self.support)
        if verdict != SUPPORTED:
            self.dropped.append(
                {"claim_id": claim_id, "verdict": verdict, "reasons": [problem.code for problem in problems]}
            )
            return None
        if kind == "mechanism" and not (
            any(self.evidence[ref]["kind"] == "news" for ref in valid)
            and any(self.evidence[ref]["kind"] == "company" for ref in valid)
        ):
            self.dropped.append(
                {"claim_id": claim_id, "verdict": "insufficient", "reasons": ["missing_event_or_company"]}
            )
            return None
        return {"claim_id": claim_id, "text": text, "evidence_refs": valid}


FAMILY_NAMES = {
    "industry": "вид деятельности",
    "geography": "регион",
    "trade": "запись ФТС",
    "scale": "масштаб",
    "group": "группа компаний",
    "stage": "стадия бизнеса",
    "product": "продукты банка",
    "profile": "прочие признаки профиля",
}
LEVEL_NAMES = {"low": "низкая", "medium": "средняя", "high": "высокая"}


def rubric_reason(level, rubric) -> str:
    factors = ", ".join(FAMILY_NAMES.get(item, item) for item in rubric.factors)
    parts = [f"Сила влияния {LEVEL_NAMES[level]} по рубрике: подтверждённые независимые факторы – {factors}"]
    parts.append(
        "связь признаков с темой события есть"
        if rubric.components["direct_event_matches"]
        else "прямой связи признаков с темой события нет"
    )
    if not rubric.components["quantified_exposure"]:
        parts.append("масштаб экспозиции числами с единицей и периодом не подтверждён")
    return "; ".join(parts) + ". Оценка качественная, это не вероятность и не сумма."


def impact_payload(
    outcome: AgentOutcome, aliases: dict[str, str], bank: list[dict], missing: list[str]
) -> str:
    prepared = outcome.prepared
    by_id = {value: key for key, value in aliases.items()}
    news: dict[str, list[str]] = {}
    for claim in prepared.facts:
        news.setdefault(by_id[claim["evidence_refs"][0]], []).append(claim["text"])
    topics = prepared.payload.topics if isinstance(prepared.payload.topics, dict) else {}
    payload = {
        "event": {
            "title": prepared.payload.title,
            "published_at": prepared.payload.published_at,
            "topics": topics,
        },
        "news": [{"id": alias, "facts": texts} for alias, texts in news.items()],
        "source_conditions": condition_context(prepared.payload, aliases),
        "mechanism_bases": mechanism_bases(prepared.company, aliases),
        "user_focus": {
            "topics": prepared.focus.get("topics", []),
            "priorities": prepared.focus.get("priorities", []),
        },
        "company_features": [
            {"id": by_id[fact.evidence_id], "text": fact.excerpt}
            for fact in prepared.company
            if fact.feature not in NON_IMPACT_FEATURES
        ],
        "profile_gaps": [str(item) for item in (prepared.context.get("unknowns") or [])][:10],
        "matched_with_event": prepared.matches,
        "bank_fragments": [
            {
                "id": by_id[item["id"]],
                "document_date": item["locator"].get("document_date"),
                "text": item["excerpt"],
            }
            for item in bank
        ],
        "known_missing_parameters": missing,
    }
    return json.dumps(payload, ensure_ascii=False)


def call_impact(prompt: str) -> tuple[RawImpact, dict | None, str | None]:
    try:
        result = call_llm(
            "build_impact",
            LLMInput(system=IMPACT_SYSTEM_PROMPT, user=prompt),
            IMPACT_TOKENS,
            response_model=RawImpact,
            temperature=0.0,
        )
    except LLMError as error:
        if error.code in FATAL_CODES:
            raise
        return RawImpact(), None, error.code
    return RawImpact.model_validate(result.data), usage_step("build_impact", result), None


def finalize(outcome: AgentOutcome, now: datetime | None = None) -> dict:
    prepared, composed = outcome.prepared, outcome.composed
    v1 = outcome.envelope
    v1_result, v1_trace = v1["result"], v1["trace"]
    event_day = event_date(prepared.payload)
    today = today_msk(now)
    news_evidence = {
        item.id: item.model_dump(mode="json") for item in prepared.payload.evidence if item.kind == "news"
    }
    bank_evidence = {item["id"]: item for item in v1["evidence"] if item["kind"] == "bank"}
    company_evidence = dict(prepared.company_ids)
    known = {**news_evidence, **company_evidence, **bank_evidence}

    bank_view_dated, undated = split_bank_view(v1_result["bank_view"], bank_evidence)
    sources_text = " ".join(
        [prepared.payload.title, prepared.payload.summary or ""]
        + [publication.text for publication in prepared.payload.publications]
        + [item["excerpt"] for item in known.values()]
    )
    bank_items = [bank_evidence[ref] for claim in bank_view_dated for ref in claim["evidence_refs"]]
    bank_items = list({item["id"]: item for item in bank_items}.values())
    aliases = aliases_for(prepared.facts, prepared.company, bank_items)
    candidates = {
        **{ref: {"kind": "news"} for ref in prepared.news_ids},
        **{ref: {"kind": "company"} for ref in company_evidence},
        **{ref: {"kind": "bank"} for ref in bank_evidence},
    }

    steps: list[dict] = []
    failure: str | None = None
    raw = RawImpact()
    if prepared.facts:
        prompt = impact_payload(outcome, aliases, bank_items, missing_parameters(prepared))
        raw, usage, failure = call_impact(prompt)
        if usage:
            steps.append(usage)
    else:
        failure = "no_event_facts"

    verifier = Verifier(prepared, composed, {**company_evidence, **bank_evidence}, candidates)
    mechanism = verifier.accept_many(
        "mechanism", raw.mechanism[:MAX_MECHANISM], aliases, "mechanism", "ai_interpretation"
    )
    summary = verifier.accept("summary", raw.summary, aliases, "hypothesis", "summary")
    impact_reason = verifier.accept("impact", raw.impact_reason, aliases, "hypothesis", "impact_reason")
    assumptions = verifier.accept_many(
        "assumption", raw.assumptions[:MAX_ASSUMPTIONS], aliases, "hypothesis", "assumption"
    )
    relevance_reason = verifier.accept(
        "relevance", raw.relevance_reason, aliases, "hypothesis", "relevance_reason"
    )

    cited = {ref for item in mechanism for ref in item["evidence_refs"] if ref in company_evidence}
    cited_features = {
        company_evidence[ref]["locator"]["feature_path"].removeprefix("features.") for ref in cited
    }
    horizon_raw = raw.horizon
    starts_on = grounded_date(horizon_raw.starts_on, sources_text)
    ends_on = grounded_date(horizon_raw.ends_on, sources_text)
    kind = horizon_raw.kind if horizon_raw.kind in {"dated", "long_term", "unknown"} else "unknown"
    if kind == "dated" and not (starts_on or ends_on):
        kind = "unknown"
    label = clean_text(horizon_raw.label)[:MAX_LABEL_CHARS]
    if not label or unsupported_numbers(label, sources_text):
        label = {"dated": "Период назван в источниках", "long_term": "Долгосрочный эффект"}.get(
            kind, "Горизонт не определён"
        )

    synthesized: list[str] = []
    if mechanism and summary is None:
        first = mechanism[0]
        summary = {
            "claim_id": "summary",
            "text": shorten(first["text"], MAX_SUMMARY_CHARS),
            "evidence_refs": first["evidence_refs"],
        }
        synthesized.append("summary")
    usable_mechanism = bool(mechanism) and summary is not None
    rubric = assess(
        raw.impact_level if usable_mechanism else "undetermined",
        prepared.context,
        cited_features,
        any(ref in news_evidence for item in mechanism for ref in item["evidence_refs"]),
        prepared.matches,
        bool(bank_view_dated),
        kind == "dated" and ends_on is not None,
    )
    level = rubric.level
    determined = level != "undetermined"
    if determined and impact_reason is None:
        impact_reason = {
            "claim_id": "impact",
            "text": rubric_reason(level, rubric),
            "evidence_refs": list(dict.fromkeys(ref for item in mechanism for ref in item["evidence_refs"])),
        }
        synthesized.append("impact_reason")
    if not usable_mechanism:
        summary = impact_reason = relevance_reason = None
        mechanism = []
        assumptions = []
    elif not determined:
        relevance_reason = None
    window = relevance_window(
        kind, starts_on, ends_on, event_day, today, determined and relevance_reason is not None
    )
    if window["relevance_status"] == "undetermined":
        relevance_reason = None

    sections = typed_sections(v1_result, bank_view_dated)
    all_claims = [
        claim
        for key in ("facts", "ai_interpretation", "risks", "opportunities", "actions")
        for claim in sections[key]
    ] + (sections["bank_view"] or [])
    typed = {
        "personalized_summary": summary
        and statement(summary["claim_id"], summary["text"], summary["evidence_refs"], "hypothesis"),
        "impact_reason": impact_reason
        and statement(
            impact_reason["claim_id"], impact_reason["text"], impact_reason["evidence_refs"], "hypothesis"
        ),
        "relevance_reason": relevance_reason
        and statement(
            relevance_reason["claim_id"],
            relevance_reason["text"],
            relevance_reason["evidence_refs"],
            "hypothesis",
        ),
        "mechanism": [
            statement(i["claim_id"], i["text"], i["evidence_refs"], "hypothesis") for i in mechanism
        ],
        "assumptions": [
            statement(i["claim_id"], i["text"], i["evidence_refs"], "hypothesis") for i in assumptions
        ],
    }
    every = (
        all_claims
        + typed["mechanism"]
        + typed["assumptions"]
        + [typed[key] for key in ("personalized_summary", "impact_reason", "relevance_reason") if typed[key]]
    )
    refs = list(dict.fromkeys(ref for claim in every for ref in claim["evidence_refs"]))

    # Final applicability gaps precede generic search gaps and survive the cap.
    unknowns = [shorten(clean_text(text), MAX_UNKNOWN_CHARS) for text in raw.unknowns]
    unknowns.extend(v1_result["unknowns"])
    if undated:
        unknowns.append(UNDATED_BANK_UNKNOWN)
    if not determined:
        reason = (
            "модель не вернула разбираемый ответ"
            if failure and failure != "no_event_facts"
            else "в событии нет проверенных фактов"
            if failure == "no_event_facts"
            else "в источниках нет подтверждённого механизма влияния"
            if not usable_mechanism
            else "; ".join(CAP_REASONS[item] for item in rubric.caps) or "доказательств недостаточно"
        )
        unknowns.insert(0, f"Сила влияния не определена: {reason}")
    else:
        unknowns.extend(
            CAP_REASONS[item]
            for item in rubric.caps
            if item in {"single_factor", "exposure_not_quantified", "trigger_not_dated"}
        )
    if window["relevance_status"] == "undetermined":
        unknowns.append("Срок актуальности вывода источниками не установлен")
    if prepared.context.get("relationships"):
        unknowns.append(RELATIONSHIP_UNKNOWN)
    unknowns = list(dict.fromkeys(item for item in unknowns if item.strip()))[:MAX_UNKNOWNS]

    result = {
        "schema_version": "v2",
        "facts": sections["facts"],
        "bank_view": sections["bank_view"],
        "ai_interpretation": sections["ai_interpretation"],
        "risks": sections["risks"],
        "opportunities": sections["opportunities"],
        "actions": sections["actions"],
        "personalized_summary": typed["personalized_summary"],
        "mechanism": typed["mechanism"],
        "impact_level": level,
        "impact_reason": typed["impact_reason"],
        "time_horizon": {
            "label": label,
            "starts_on": starts_on.isoformat() if starts_on else None,
            "ends_on": ends_on.isoformat() if ends_on else None,
        },
        "assumptions": typed["assumptions"],
        "relevance_status": window["relevance_status"],
        "valid_from": window["valid_from"].isoformat() if window["valid_from"] else None,
        "valid_until": window["valid_until"].isoformat() if window["valid_until"] else None,
        "review_after": window["review_after"].isoformat() if window["review_after"] else None,
        "relevance_reason": typed["relevance_reason"],
        "bank_view_context": bank_context(sections["bank_view"], bank_evidence, event_day),
        "next_actions": next_actions(determined),
        **policy_fields(),
        "unknowns": unknowns,
        "evidence_refs": refs,
        "trace_id": v1_result["trace_id"],
    }
    evidence = [
        {key: known[ref][key] for key in ("id", "kind", "source_id", "version", "locator", "excerpt")}
        for ref in refs
    ]
    trace = {
        **v1_trace,
        "schema_version": "v2",
        "contract_versions": contract_versions(prepared.context.get("data_semantics_version")),
        "impact": {
            "prompt_version": IMPACT_PROMPT_VERSION,
            "rubric_version": RUBRIC_VERSION,
            "proposed_level": raw.impact_level,
            "level": level,
            "rubric": rubric.components,
            "caps": rubric.caps,
            "failure": failure,
            "dropped_statements": verifier.dropped,
            "cited_features": sorted(cited_features),
            "synthesized": synthesized,
            "horizon_kind": kind,
            "assumptions": [item["claim_id"] for item in assumptions],
            "usage": steps,
        },
        "steps": [*v1_trace["steps"], *steps],
    }
    return InsightEnvelopeV2.model_validate(
        {"result": result, "evidence": evidence, "trace": trace}
    ).model_dump(mode="json")


def build_impact_insight(
    company_context: dict, user_focus: dict, event: dict, tools, now: datetime | None = None
) -> dict:
    return finalize(run_agent_detailed(company_context, user_focus, event, tools), now)

from dataclasses import dataclass, field

from app.ai.agent.prompts import AGENT_PROMPT_VERSION
from app.ai.agent.steps import (
    CheckResult,
    bank_ids_of,
    check_card,
    make_plan,
    next_query,
    verify_bank_claims,
)
from app.ai.insights.build import (
    SEARCH_LIMIT,
    Composed,
    Prepared,
    assemble_envelope,
    base_steps,
    compose_card,
    event_date,
    prepare_insight,
)

MAX_EXTRA_SEARCHES = 2


@dataclass
class AgentRun:
    prepared: Prepared
    tools: object
    steps: list[dict] = field(default_factory=list)
    hits: dict[str, dict] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    outcomes: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    extra_searches: int = 0
    iterations: int = 0

    def search(self, query: str, purpose: str) -> int:
        as_of = event_date(self.prepared.payload).isoformat()
        found = self.tools.search_bank_analytics(query, as_of, SEARCH_LIMIT)
        items = found.get("items", [])
        fresh = [item for item in items if item["chunk_id"] not in self.hits]
        for item in items:
            self.hits.setdefault(item["chunk_id"], item)
        usable = [item for item in items if not item["historical"]]
        self.queries.append(query)
        self.outcomes.append({"query": query, "returned": len(items), "usable": len(usable)})
        self.steps.append(
            {
                "tool": "search_bank_analytics",
                "purpose": purpose,
                "query": query,
                "as_of": as_of,
                "returned": [
                    {"chunk_id": item["chunk_id"], "page": item["page"], "historical": item["historical"]}
                    for item in items
                ],
                "evidence_ids": bank_ids_of(usable),
                "new_fragments": len(fresh),
                "empty_reason": found.get("empty_reason"),
            }
        )
        return len(fresh)

    def ordered_hits(self) -> list[dict]:
        return sorted(
            self.hits.values(), key=lambda item: (item["historical"], item["date_unknown"], -item["score"])
        )

    def evaluate(self) -> tuple[Composed, CheckResult]:
        self.iterations += 1
        composed = compose_card(self.prepared, self.ordered_hits())
        self.steps.extend(composed.usage_steps)
        composed, rejected, extra_usage = verify_bank_claims(self.prepared, composed)
        self.steps.extend(extra_usage)
        check = check_card(self.prepared, composed, rejected)
        claim_ids = [claim["claim_id"] for items in composed.sections.values() for claim in items]
        evidence_ids = sorted(
            {ref for items in composed.sections.values() for claim in items for ref in claim["evidence_refs"]}
        )
        record = {
            "iteration": self.iterations,
            "status": check.status,
            "reasons": check.reasons,
            "rejected_bank_claims": rejected,
            "claims": claim_ids,
            "evidence_ids": evidence_ids,
        }
        self.checks.append(record)
        self.steps.append(
            {"check": check.status, **{key: record[key] for key in ("iteration", "reasons", "evidence_ids")}}
        )
        return composed, check


def stop_unknowns(stop_reason: str, check: CheckResult, queries: list[str], extra: int) -> list[str]:
    if stop_reason != "retry_limit_reached":
        return []
    asked = "; ".join(f"«{query}»" for query in queries)
    verdicts = ", ".join(item["detail"] for item in check.reasons)
    return [
        f"Позиция банка по событию не подтверждена: после {extra} уточняющих поисков подходящих материалов нет ({verdicts}), запросы: {asked}"
    ]


def run_agent(
    company_context: dict,
    user_focus: dict,
    event: dict,
    tools,
    max_extra_searches: int = MAX_EXTRA_SEARCHES,
) -> dict:
    prepared = prepare_insight(company_context, user_focus, event, tools)
    run = AgentRun(prepared, tools)
    run.steps.extend(base_steps(prepared))
    if not prepared.facts:
        composed = compose_card(prepared, [])
        run.steps.append({"stop": "no_event_facts"})
        return assemble_envelope(
            prepared,
            composed,
            run.steps,
            ["read_event_facts"],
            "no_event_facts",
            extra_trace=trace_fields(run, "no_event_facts"),
        )
    plan, first_queries, plan_usage = make_plan(prepared)
    run.steps.append({"plan": plan, "initial_queries": first_queries})
    run.steps.extend(plan_usage)
    for query in first_queries:
        run.search(query, "initial")
    composed, check = run.evaluate()
    signature_before = signature_of(run.hits)
    stop_reason = "supported"
    while check.status != "supported":
        if not check.searchable:
            stop_reason = "no_further_search_possible"
            break
        if run.extra_searches >= max_extra_searches:
            stop_reason = "retry_limit_reached"
            break
        query, reason, usage = next_query(prepared, run.queries, check, run.outcomes)
        run.steps.extend(usage)
        if not query:
            stop_reason = "retry_limit_reached"
            break
        run.steps.append(
            {
                "retry": run.extra_searches + 1,
                "after_check": check.status,
                "previous_queries": list(run.queries),
                "new_query": query,
                "reason": reason,
            }
        )
        run.search(query, "retry")
        run.extra_searches += 1
        if signature_of(run.hits) != signature_before:
            signature_before = signature_of(run.hits)
            composed, check = run.evaluate()
    run.steps.append(
        {"stop": stop_reason, "iterations": run.iterations, "extra_searches": run.extra_searches}
    )
    return assemble_envelope(
        prepared,
        composed,
        run.steps,
        [*plan, "check_grounding", "retry_search_if_needed"],
        stop_reason,
        extra_unknowns=stop_unknowns(stop_reason, check, run.queries, run.extra_searches),
        extra_trace=trace_fields(run, stop_reason),
        drop_bank_view=False,
    )


def signature_of(hits: dict) -> frozenset[str]:
    return frozenset(chunk_id for chunk_id, hit in hits.items() if not hit["historical"])


def trace_fields(run: AgentRun, stop_reason: str) -> dict:
    return {
        "agent_version": AGENT_PROMPT_VERSION,
        "iterations": run.iterations,
        "extra_searches": run.extra_searches,
        "queries": run.queries,
        "checks": run.checks,
        "stop_reason": stop_reason,
    }

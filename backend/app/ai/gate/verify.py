import json

from pydantic import Field

from app.ai.gate.prompts import GATE_SYSTEM_PROMPT, PART_KINDS
from app.ai.lenient import Lenient
from app.ai.providers import LLMError, LLMInput, call_llm

GATE_TASK = "gate_verify"
BATCH = 6
MAX_TOKENS = 3800
VERDICTS = frozenset({"supported", "unsupported", "contradicted"})
PASSING_PARTS = frozenset({"in_sources", "acceptable_condition"})
PART_STATUSES = PASSING_PARTS | {"not_in_sources", "contradicted"}
KNOWN_KINDS = frozenset(item.strip() for item in PART_KINDS.split(","))
MIN_PART_CHARS = 3
SEVERITY = {"supported": 0, "unsupported": 1, "contradicted": 2}
UNVERIFIED = "unverified"


class RawPart(Lenient):
    text: str = ""
    kind: str = ""
    actor_in_claim: str = ""
    actor_in_source: str = ""
    status: str = ""


class RawVerdict(Lenient):
    id: str = ""
    verdict: str = ""
    reason: str = ""
    parts: list[RawPart] = Field(default_factory=list)


class RawVerdicts(Lenient):
    verdicts: list[RawVerdict] = Field(default_factory=list)


def source_label(item: dict) -> dict:
    locator = item.get("locator") or {}
    label = {"kind": item["kind"], "text": item["text"]}
    if item["kind"] == "bank":
        label["document"] = locator.get("title")
        label["date"] = locator.get("document_date")
        label["page"] = locator.get("page")
    return label


def meaningful(parts: list[RawPart]) -> bool:
    return bool(parts) and all(
        len(part.text.strip()) >= MIN_PART_CHARS and part.kind in KNOWN_KINDS and part.status in PART_STATUSES
        for part in parts
    )


def decided(item: RawVerdict) -> dict:
    derived = "supported"
    failing = None
    for part in item.parts:
        if part.status == "contradicted":
            derived, failing = "contradicted", failing or part
        elif part.status not in PASSING_PARTS:
            derived = derived if derived == "contradicted" else "unsupported"
            failing = failing or part
    final = max(derived, item.verdict, key=lambda value: SEVERITY[value])
    reason = item.reason[:240] if final == item.verdict or failing is None else failing.text[:240]
    return {"verdict": final, "reason": reason, "parts": [part.model_dump() for part in item.parts]}


FATAL_CODES = frozenset({"budget_exhausted", "model_not_allowed", "ai_unavailable"})


def judge_batch(
    batch: list[dict],
    sources: dict[str, dict],
    rejected_premises: list[str],
    task: str,
    system: str,
    verdicts: dict[str, dict],
    usage: list[dict],
) -> None:
    payload = {
        "rejected_premises": rejected_premises,
        "claims": [
            {
                "id": claim["claim_id"],
                "section": claim["section"],
                "statement_type": claim["statement_type"],
                "text": claim["text"],
                "sources": [source_label(sources[ref]) for ref in claim["evidence_refs"] if ref in sources],
            }
            for claim in batch
        ],
    }
    try:
        result = call_llm(
            task,
            LLMInput(system=system, user=json.dumps(payload, ensure_ascii=False)),
            MAX_TOKENS,
            response_model=RawVerdicts,
            temperature=0.0,
        )
    except LLMError as error:
        if error.code != "invalid_json":
            raise
        if len(batch) > 1:
            middle = len(batch) // 2
            judge_batch(batch[:middle], sources, rejected_premises, task, system, verdicts, usage)
            judge_batch(batch[middle:], sources, rejected_premises, task, system, verdicts, usage)
            return
        verdicts[batch[0]["claim_id"]] = {
            "verdict": UNVERIFIED,
            "reason": "ответ проверяющего не удалось разобрать",
        }
        return
    usage.append(
        {
            "llm": task,
            "request_id": result.request_id,
            "model": result.model_id,
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cost_rub": result.usage.cost_rub,
        }
    )
    given = {item.id: item for item in RawVerdicts.model_validate(result.data).verdicts}
    for claim in batch:
        item = given.get(claim["claim_id"])
        if item is None:
            verdicts[claim["claim_id"]] = {
                "verdict": UNVERIFIED,
                "reason": "проверяющий не вернул вердикт по этому утверждению",
            }
        elif item.verdict in VERDICTS and meaningful(item.parts):
            verdicts[claim["claim_id"]] = decided(item)
        elif item.verdict in VERDICTS:
            verdicts[claim["claim_id"]] = {
                "verdict": UNVERIFIED,
                "reason": "проверяющий не разобрал утверждение на содержательные части",
            }
        else:
            verdicts[claim["claim_id"]] = {
                "verdict": UNVERIFIED,
                "reason": f"неизвестный вердикт проверки: {item.verdict[:40]}",
            }


def verify_claims(
    claims: list[dict],
    sources: dict[str, dict],
    rejected_premises: list[str] | None = None,
    task: str = GATE_TASK,
    system: str = GATE_SYSTEM_PROMPT,
) -> tuple[dict[str, dict], list[dict]]:
    verdicts: dict[str, dict] = {}
    usage: list[dict] = []
    for start in range(0, len(claims), BATCH):
        judge_batch(
            claims[start : start + BATCH], sources, rejected_premises or [], task, system, verdicts, usage
        )
    return verdicts, usage


def verify_checked(
    claims: list[dict], sources: dict[str, dict], rejected_premises: list[str] | None = None
) -> tuple[dict[str, dict], list[dict]]:
    from app.ai.gate.guards import apply_bank_guard

    verdicts, usage = verify_claims(claims, sources, rejected_premises)
    return apply_bank_guard(claims, sources, verdicts), usage

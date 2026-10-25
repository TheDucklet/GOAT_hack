import json

from pydantic import Field

from app.ai.gate.prompts import GATE_SYSTEM_PROMPT
from app.ai.providers import LLMInput, call_llm
from app.ai.summarization.summarize import Lenient

GATE_TASK = "gate_verify"
BATCH = 12
MAX_TOKENS = 2200
VERDICTS = frozenset({"supported", "unsupported", "contradicted"})
UNVERIFIED = "unverified"


class RawVerdict(Lenient):
    id: str = ""
    verdict: str = ""
    reason: str = ""


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


def verify_claims(
    claims: list[dict], sources: dict[str, dict], rejected_premises: list[str] | None = None
) -> tuple[dict[str, dict], list[dict]]:
    verdicts: dict[str, dict] = {}
    usage: list[dict] = []
    for start in range(0, len(claims), BATCH):
        batch = claims[start : start + BATCH]
        payload = {
            "rejected_premises": rejected_premises or [],
            "claims": [
                {
                    "id": claim["claim_id"],
                    "section": claim["section"],
                    "statement_type": claim["statement_type"],
                    "text": claim["text"],
                    "sources": [
                        source_label(sources[ref]) for ref in claim["evidence_refs"] if ref in sources
                    ],
                }
                for claim in batch
            ],
        }
        result = call_llm(
            GATE_TASK,
            LLMInput(system=GATE_SYSTEM_PROMPT, user=json.dumps(payload, ensure_ascii=False)),
            MAX_TOKENS,
            response_model=RawVerdicts,
            temperature=0.0,
        )
        usage.append(
            {
                "llm": GATE_TASK,
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
            elif item.verdict in VERDICTS:
                verdicts[claim["claim_id"]] = {"verdict": item.verdict, "reason": item.reason[:240]}
            else:
                verdicts[claim["claim_id"]] = {
                    "verdict": UNVERIFIED,
                    "reason": f"неизвестный вердикт проверки: {item.verdict[:40]}",
                }
    return verdicts, usage

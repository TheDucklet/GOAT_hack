"""Publication gate contract shared by the AI module and the backend.

The AI module builds the report after its checks, the backend recomputes everything it can from the
result itself and refuses to store anything the report does not fully cover.
"""

import hashlib
import json
import re

PUBLICATION_POLICY_VERSION = "publication-1"
SERVICE_ANSWER_KIND = "service_message"
INSIGHT_SECTIONS = (
    "facts",
    "bank_view",
    "ai_interpretation",
    "risks",
    "opportunities",
    "actions",
    "mechanism",
    "assumptions",
)
INSIGHT_SINGLE = ("personalized_summary", "impact_reason", "relevance_reason")
CRITICAL_SECTIONS = ("facts", "bank_view")
DIGEST_EXCLUDED = ("trace_id",)


def content_digest(result: dict) -> str:
    kept = {key: value for key, value in result.items() if key not in DIGEST_EXCLUDED}
    text = json.dumps(kept, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def insight_claims(result: dict) -> list[dict]:
    claims = []
    for section in INSIGHT_SECTIONS:
        for claim in result.get(section) or []:
            claims.append({**claim, "section": section})
    for section in INSIGHT_SINGLE:
        claim = result.get(section)
        if claim:
            claims.append({**claim, "section": section})
    return claims


def answer_sentences(text: str) -> list[str]:
    parts = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if item.strip()]
    return parts


def chat_claims(result: dict) -> list[dict]:
    return [
        {
            "claim_id": f"answer-{number}",
            "section": "answer",
            "statement_type": "hypothesis",
            "text": sentence,
            "evidence_refs": list(result.get("evidence_refs", [])),
        }
        for number, sentence in enumerate(answer_sentences(result.get("answer", "")), start=1)
    ]


def report_problems(report: dict | None, result: dict, evidence: list[dict], kind: str) -> list[str]:
    if not isinstance(report, dict):
        return ["отчёт проверки отсутствует"]
    problems = []
    if report.get("policy_version") != PUBLICATION_POLICY_VERSION:
        problems.append("версия политики проверки не совпадает с текущей")
    if report.get("decision") != "allow":
        problems.append("допуск к публикации не выдан")
    if report.get("decided_by") != "code":
        problems.append("допуск вычислен не кодом")
    if report.get("content_digest") != content_digest(result):
        problems.append("отчёт относится к другому содержимому результата")
    required = insight_claims(result) if kind == "insight" else chat_claims(result)
    entries = report.get("claims") or []
    expected = {(item["claim_id"], item["section"]) for item in required}
    found = {(item.get("claim_id"), item.get("section")) for item in entries}
    if len(entries) != len(found) or expected != found:
        problems.append("проверены не все обязательные утверждения")
    if any(item.get("verdict") != "supported" for item in entries):
        problems.append("есть утверждение без положительного вердикта")
    if report.get("unresolved_critical"):
        problems.append("остались неразрешённые критические ошибки")
    counts = (report.get("required"), report.get("checked"), report.get("supported"))
    if not (counts[0] == counts[1] == counts[2] == len(expected)):
        problems.append("покрытие проверки неполное")
    known = {item["id"]: item for item in evidence}
    for entry in entries:
        for ref in entry.get("evidence", []):
            if ref.get("id") not in known or known[ref["id"]].get("version") != ref.get("version"):
                problems.append("версия основания в отчёте не совпадает с основанием результата")
                break
    if kind == "insight" and not result.get("facts"):
        problems.append("в результате нет проверенных фактов")
    return list(dict.fromkeys(problems))

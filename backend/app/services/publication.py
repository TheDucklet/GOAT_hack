from app.integrations.ai import AIError
from app.publication_policy import SERVICE_ANSWER_KIND, report_problems, service_problems


def require_publication(envelope, result: dict, kind: str) -> str:
    report = envelope.trace.get("publication") if isinstance(envelope.trace, dict) else None
    evidence = [item.model_dump(mode="json") for item in envelope.evidence]
    if kind == "chat" and isinstance(report, dict) and report.get("decision") == SERVICE_ANSWER_KIND:
        if service_problems(report, result, evidence):
            raise AIError("invalid_publication_report", "Служебное сообщение не прошло проверку формата")
        return SERVICE_ANSWER_KIND
    if isinstance(report, dict) and report.get("decision") == "block":
        reason = report.get("stop_reason") or "quality_gate"
        raise AIError("quality_gate_blocked", f"Результат не прошёл проверку перед публикацией: {reason}")
    problems = report_problems(report, result, evidence, kind)
    if problems:
        raise AIError("invalid_publication_report", "; ".join(problems))
    return "allow"

"""One bounded semantic repair; every generated answer passes the same publication gate."""

from app.ai.chat.answer import answer_chat, usage_total
from app.ai.gate.chat import enforce_chat
from app.ai.gate.pipeline import news_texts


def build_published_answer(company_context, user_focus, event, history, tools) -> dict:
    original = answer_chat(company_context, user_focus, event, history, tools)
    first = enforce_chat(original, news_texts(event))
    report = first["trace"]["publication"]
    rejected = report.get("removed") or []
    actionable = [item for item in rejected if item["verdict"] in {"unsupported", "contradicted"}]
    if (
        original["trace"].get("intent") not in {"importance", "missing_data"}
        or report["decision"] == "allow"
        or not actionable
    ):
        return first
    repaired = answer_chat(
        company_context,
        user_focus,
        event,
        history,
        tools,
        publication_feedback=actionable,
    )
    repaired["trace"]["steps"] = original["trace"]["steps"] + repaired["trace"]["steps"]
    repaired["result"]["usage"] = usage_total(repaired["trace"]["steps"])
    final = enforce_chat(repaired, news_texts(event))
    final["trace"]["chat_repair"] = {"attempts": 1, "first_publication": report}
    final["trace"]["total_usage"] = usage_total(
        repaired["trace"]["steps"] + report["usage"] + final["trace"]["publication"]["usage"]
    )
    return final

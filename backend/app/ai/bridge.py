from app.ai.agent.runner import run_agent
from app.ai.chat.answer import answer_chat
from app.ai.ocr.ingest import ingest_bank_document
from app.ai.personalization.focus import derive_user_focus
from app.ai.rag.search import search_bank_analytics
from app.ai.summarization.summarize import summarize_event

__all__ = [
    "answer_chat",
    "build_insight",
    "derive_user_focus",
    "ingest_bank_document",
    "search_bank_analytics",
    "summarize_event",
]


def build_insight(company_context: dict, user_focus: dict, event: dict, tools) -> dict:
    return run_agent(company_context, user_focus, event, tools)

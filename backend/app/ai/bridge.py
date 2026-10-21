from app.ai.cache.calls import cached_build_insight, cached_derive_user_focus, cached_summarize_event
from app.ai.chat.answer import answer_chat
from app.ai.ocr.ingest import ingest_bank_document
from app.ai.rag.search import search_bank_analytics

__all__ = [
    "answer_chat",
    "build_insight",
    "derive_user_focus",
    "ingest_bank_document",
    "search_bank_analytics",
    "summarize_event",
]


def build_insight(company_context: dict, user_focus: dict, event: dict, tools) -> dict:
    return cached_build_insight(company_context, user_focus, event, tools)


def derive_user_focus(position_text: str, interests: list[str]) -> dict:
    return cached_derive_user_focus(position_text, interests)


def summarize_event(event: dict) -> dict:
    return cached_summarize_event(event)

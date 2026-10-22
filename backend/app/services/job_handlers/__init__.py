"""The single job registry: handler plus whether an initiating user must be admin."""

from .analysis import chat_job, focus_job, insight_job
from .documents import ingest_document_job
from .feed import prepare_feed_job
from .news import collect_news_job, summarize_job

HANDLERS = {
    "collect_news": (collect_news_job, True),
    "summarize": (summarize_job, True),
    "ingest_document": (ingest_document_job, True),
    "focus": (focus_job, False),
    "insight": (insight_job, False),
    "chat": (chat_job, False),
    "feed_prepare": (prepare_feed_job, False),
}

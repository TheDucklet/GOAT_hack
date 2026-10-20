from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import CompanyContext, EvidenceOut, UserFocus

MAX_QUERY_CHARS = 1000


class AIInput(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Publication(AIInput):
    id: str
    url: str
    text: str


class EventPayload(AIInput):
    id: str
    title: str
    summary: str | None = None
    published_at: str | None = None
    version: str
    topics: dict[str, list[str]] | list[str] | None = None
    facts: list[dict] | None = None
    publications: list[Publication]
    evidence: list[EvidenceOut]


class DocumentRef(AIInput):
    id: str
    version: str
    page_count: int = Field(ge=1)
    filename: str


class ChatTurn(AIInput):
    role: Literal["user", "assistant"]
    text: str


class DeriveUserFocusInput(AIInput):
    position_text: str = Field(default="", max_length=1000)
    interests: list[str] = Field(default_factory=list, max_length=30)


class SummarizeEventInput(AIInput):
    event: EventPayload


class IngestBankDocumentInput(AIInput):
    document: DocumentRef
    path: str


class SearchBankAnalyticsInput(AIInput):
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    as_of: date
    limit: int = Field(default=5, ge=1, le=5)


class BuildInsightInput(AIInput):
    company_context: CompanyContext
    user_focus: UserFocus
    event: EventPayload


class AnswerChatInput(BuildInsightInput):
    history: list[ChatTurn] = Field(min_length=1)

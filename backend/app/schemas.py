from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ErrorOut(Schema):
    code: str
    message: str
    request_id: str
    field_errors: list[dict] = []


class Credentials(Schema):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class LoginCredentials(Schema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserOut(Schema):
    id: str
    email: str
    system_role: Literal["user", "admin"]
    status: Literal["active", "blocked"]


class MembershipOut(Schema):
    id: str
    user_id: str
    company_id: str
    position_text: str
    interests: list[str]
    status: Literal["pending", "active", "rejected"]


class MeOut(UserOut):
    memberships: list[MembershipOut]
    csrf_token: str


class ProfileIn(Schema):
    position_text: str = Field(default="", max_length=1000)
    interests: list[str] = Field(default_factory=list, max_length=30)


class MembershipIn(ProfileIn):
    company_id: str = Field(min_length=1, max_length=100)


class MembershipPatch(Schema):
    status: Literal["active", "rejected"]


class UserPatch(Schema):
    status: Literal["active", "blocked"] | None = None
    system_role: Literal["user", "admin"] | None = None


class CompanyOut(Schema):
    id: str
    name: str
    profile_version: str


class CompanyContext(Schema):
    company_id: str
    profile_version: str
    group_id: str | None
    features: dict[str, Any]
    unknowns: list[str]
    payment_links: dict[str, list[dict]]
    related_companies: list[str]


class JobOut(Schema):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    result: dict | None = None
    error: dict | None = None


class Claim(Schema):
    claim_id: str
    text: str
    evidence_refs: list[str]


class UserFocus(Schema):
    topics: list[str] = []
    priorities: list[str] = []
    unknowns: list[str] = []
    version: str


class EvidenceOut(Schema):
    id: str
    kind: Literal["news", "bank", "company"]
    source_id: str
    version: str
    locator: dict
    excerpt: str


class InsightResult(Schema):
    facts: list[Claim]
    bank_view: list[Claim] | None
    ai_interpretation: list[Claim]
    risks: list[Claim]
    opportunities: list[Claim]
    actions: list[Claim]
    unknowns: list[str]
    evidence_refs: list[str]
    trace_id: str


class InsightOut(Schema):
    id: str
    company_id: str
    event_id: str
    versions: dict
    result: InsightResult


class EventIn(Schema):
    event_id: str


class ChatIn(EventIn):
    company_id: str


class ChatOut(Schema):
    id: str
    company_id: str
    event_id: str


class MessageIn(Schema):
    text: str = Field(min_length=1, max_length=10000)


class MessageOut(Schema):
    id: str
    chat_id: str
    sequence: int
    role: Literal["user", "assistant"]
    text: str
    result: dict | None
    created_at: datetime


class ChatResult(Schema):
    answer: str
    evidence_refs: list[str]
    unknowns: list[str]
    trace_id: str
    usage: dict = {}


class FeedbackIn(Schema):
    insight_id: str
    rating: Literal[-1, 1]
    comment: str = Field(default="", max_length=2000)


class VisibilityIn(Schema):
    visible: bool


class FeedItem(Schema):
    event_id: str
    title: str
    summary: str | None
    published_at: datetime | None
    rank_score: float
    relevance_reasons: list[dict]
    status: str
    sources: list[dict]


class FeedOut(Schema):
    items: list[FeedItem]
    total: int
    limit: int
    offset: int


class DocumentOut(Schema):
    id: str
    filename: str
    version: str
    document_date: str | None
    page_count: int
    status: str
    error: str | None


class UploadOut(Schema):
    document: DocumentOut
    job: JobOut | None
    source_id: str | None = None


class StatsOut(Schema):
    positive_feedback: int
    negative_feedback: int
    failed_jobs: int


class FeedbackOut(Schema):
    id: str
    rating: Literal[-1, 1]


class VisibilityOut(Schema):
    id: str
    visible: bool


class AdminEventOut(VisibilityOut):
    title: str
    published_at: datetime | None
    processing_status: str
    sources: list[dict]


class SummaryResult(Schema):
    summary: str
    facts: list[Claim]
    entities: list[str] = []
    topics: dict[str, list[str]]


class IngestResult(Schema):
    document_date: str | None = None
    chunks: list[dict]


class AIEnvelope(Schema):
    result: dict
    evidence: list[EvidenceOut] = []
    trace: dict = {}

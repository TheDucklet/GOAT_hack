from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.notice_policy import DISCLAIMER, POLICY_VERSION


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


class DataFeature(Schema):
    raw: list[str]
    normalized: str | None
    value: str | None
    quality: Literal["confirmed", "assumed", "conflicting", "missing", "invalid", "quarantined", "legacy"]
    provenance: dict
    unit: str | None
    period: str | None
    issues: list[str]

    @model_validator(mode="after")
    def safe_projection(self):
        if self.quality != "confirmed" and self.value is not None:
            raise ValueError("uncertain features cannot expose a confirmed value")
        if self.quality == "confirmed" and (self.value is None or self.value != self.normalized):
            raise ValueError("confirmed value must equal its normalized value")
        return self


class PaymentTotals(Schema):
    amount: str
    payment_count: int
    row_count: int


class PaymentSummary(Schema):
    outgoing: PaymentTotals
    incoming: PaymentTotals
    self_payments: PaymentTotals
    quarantined: PaymentTotals
    unclassified: PaymentTotals
    unit: str | None
    period: str | None
    provenance: dict


class CompanyRelationship(Schema):
    company_id: str
    relation_type: Literal["same_group", "shared_person", "payment"]
    direction: Literal["incoming", "outgoing"] | None = None
    provenance: dict


class GroupSummary(Schema):
    group_id: str | None
    observed_members: int
    revenue_covered_members: int
    revenue_sum: str | None
    unit: str | None
    period: str | None
    is_consolidated: Literal[False] = False
    coverage_scope: Literal["observed_dataset"] = "observed_dataset"


class CompanyContextV2(CompanyContext):
    schema_version: Literal["v2"]
    data_semantics_version: str
    identity_quality: Literal["confirmed", "ambiguous", "placeholder", "legacy"]
    client_type: Literal["Client", "Prospect", "Closed Client"] | None
    features: dict[str, DataFeature]
    payment_summary: PaymentSummary
    relationships: list[CompanyRelationship]
    relationship_coverage: dict
    group_summary: GroupSummary


class JobOut(Schema):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    result: dict | None = None
    error: dict | None = None
    received_at: datetime | None = None
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    ready_at: datetime | None = None
    attempts: int = 0
    trace_id: str | None = None


class AdminJobOut(JobOut):
    kind: str
    target_id: str | None = None


class DismissalIn(Schema):
    event_id: str = Field(min_length=1, max_length=36)
    insight_id: str | None = Field(default=None, min_length=1, max_length=36)
    hidden: bool
    version: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def restore_version_only(self):
        if self.version is not None and (self.hidden or self.insight_id is not None):
            raise ValueError("version is only accepted for restoration without insight_id")
        return self


class DismissalOut(Schema):
    event_id: str
    version: str
    hidden: bool
    title: str | None = None


class DemoActionIn(Schema):
    event_id: str = Field(min_length=1, max_length=36)
    insight_id: str | None = Field(default=None, min_length=1, max_length=36)
    action_type: Literal["contact_manager"]
    idempotency_key: str = Field(min_length=8, max_length=100)


class DemoActionOut(Schema):
    id: str
    company_id: str
    event_id: str
    insight_id: str | None
    action_type: Literal["contact_manager"]
    mode: Literal["demo"]
    status: Literal["recorded"]
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class ProductEventIn(Schema):
    event_id: str = Field(min_length=1, max_length=36)
    insight_id: str = Field(min_length=1, max_length=36)
    event_type: Literal["impression", "open"]


class ProductEventOut(Schema):
    id: str
    event_type: str
    recorded: bool
    excluded_reason: str | None


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


NonBlank = Annotated[str, Field(min_length=1, pattern=r"\S")]
References = Annotated[list[NonBlank], Field(min_length=1)]


class ScenarioInput(Schema):
    name: NonBlank
    value: float = Field(allow_inf_nan=False, strict=True)
    unit: NonBlank
    period: NonBlank
    input_refs: References


class ScenarioRange(Schema):
    lower: float = Field(allow_inf_nan=False, strict=True)
    upper: float = Field(allow_inf_nan=False, strict=True)

    @model_validator(mode="after")
    def ordered(self):
        if self.lower > self.upper:
            raise ValueError("scenario range must be ordered")
        return self


class QuantitativeScenario(Schema):
    inputs: list[ScenarioInput] = Field(min_length=1)
    formula: NonBlank
    unit: NonBlank
    period: NonBlank
    assumptions: list[NonBlank] = Field(min_length=1)
    result_range: ScenarioRange

    @model_validator(mode="after")
    def unique_inputs(self):
        names = [item.name for item in self.inputs]
        if len(names) != len(set(names)):
            raise ValueError("scenario input names must be unique")
        return self


class StatementV2(Claim):
    claim_id: NonBlank
    text: NonBlank
    evidence_refs: References
    statement_type: Literal["fact", "hypothesis", "scenario"]
    quantitative_scenario: QuantitativeScenario | None = None

    @model_validator(mode="after")
    def scenario_has_provenance(self):
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("statement evidence_refs must be unique")
        if self.quantitative_scenario:
            if self.statement_type != "scenario":
                raise ValueError("quantitative calculation must be labelled scenario")
            refs = {ref for item in self.quantitative_scenario.inputs for ref in item.input_refs}
            if not refs.issubset(self.evidence_refs):
                raise ValueError("scenario input_refs must be included in statement evidence_refs")
        return self


class TimeHorizon(Schema):
    label: NonBlank
    starts_on: date | None
    ends_on: date | None

    @model_validator(mode="after")
    def ordered(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("time horizon must be ordered")
        return self


class NextAction(Schema):
    action: Literal["ask_question", "contact_manager_demo", "hide_insight"]
    label: NonBlank
    question: NonBlank | None = None

    @model_validator(mode="after")
    def question_only_for_chat(self):
        if (self.action == "ask_question") != (self.question is not None):
            raise ValueError("only ask_question requires question text")
        return self


class BankViewContext(Schema):
    status: Literal["current", "historical", "missing", "undated"]
    document_dates: list[date]

    @model_validator(mode="after")
    def dated_status(self):
        if bool(self.document_dates) != (self.status in {"current", "historical"}):
            raise ValueError("current/historical bank view requires document dates")
        return self


class InsightResultV2(InsightResult):
    """Canonical v2 wire contract shared by AI, API and generated UI types."""

    schema_version: Literal["v2"]
    facts: list[StatementV2]
    bank_view: list[StatementV2] | None
    ai_interpretation: list[StatementV2]
    risks: list[StatementV2]
    opportunities: list[StatementV2]
    actions: list[StatementV2]
    personalized_summary: StatementV2 | None
    mechanism: list[StatementV2]
    impact_level: Literal["low", "medium", "high", "undetermined"]
    impact_reason: StatementV2 | None
    time_horizon: TimeHorizon
    assumptions: list[StatementV2]
    relevance_status: Literal["active", "review_required", "expired", "undetermined"]
    valid_from: date | None
    valid_until: date | None
    review_after: date | None
    relevance_reason: StatementV2 | None
    bank_view_context: BankViewContext
    next_actions: list[NextAction]
    policy_version: Literal[POLICY_VERSION] = POLICY_VERSION
    disclaimer: Literal[DISCLAIMER] = DISCLAIMER
    trace_id: NonBlank

    def claims(self) -> list[StatementV2]:
        sections = [
            self.facts,
            self.bank_view or [],
            self.ai_interpretation,
            self.risks,
            self.opportunities,
            self.actions,
            self.mechanism,
            self.assumptions,
        ]
        claims = [claim for section in sections for claim in section]
        return claims + [
            claim
            for claim in (self.personalized_summary, self.impact_reason, self.relevance_reason)
            if claim is not None
        ]

    @model_validator(mode="after")
    def consistent_v2(self):
        claims = self.claims()
        ids = [claim.claim_id for claim in claims]
        if len(set(ids)) != len(ids):
            raise ValueError("claim_id must be unique across all v2 fields")
        used = {ref for claim in claims for ref in claim.evidence_refs}
        if set(self.evidence_refs) != used or len(self.evidence_refs) != len(used):
            raise ValueError("evidence_refs must equal the unique union across all v2 fields")
        if any(claim.statement_type != "fact" for claim in self.facts + (self.bank_view or [])):
            raise ValueError("facts and bank_view must contain facts only")
        if any(claim.statement_type == "fact" for claim in self.assumptions):
            raise ValueError("assumptions cannot be presented as facts")
        if self.impact_level != "undetermined" and not (
            self.impact_reason and self.personalized_summary and self.mechanism
        ):
            raise ValueError("determined impact needs a grounded summary, mechanism and reason")
        if self.impact_level == "undetermined" and not self.unknowns:
            raise ValueError("undetermined impact requires unknowns")
        if self.bank_view == []:
            raise ValueError("missing bank_view must be null")
        if (self.bank_view is None) != (self.bank_view_context.status == "missing"):
            raise ValueError("bank_view and its status must agree")
        if (self.bank_view is None or not self.facts) and not self.unknowns:
            raise ValueError("missing facts/bank view require unknowns")
        if self.relevance_status == "undetermined" and not self.unknowns:
            raise ValueError("undetermined relevance requires unknowns")
        if self.relevance_status != "undetermined" and self.relevance_reason is None:
            raise ValueError("determined relevance requires a grounded reason")
        if self.relevance_status == "active" and self.valid_from is None:
            raise ValueError("active insight requires valid_from")
        if self.relevance_status == "expired" and self.valid_until is None:
            raise ValueError("expired insight requires valid_until")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("validity interval must be ordered")
        if self.review_after and self.valid_from and self.review_after < self.valid_from:
            raise ValueError("review_after cannot precede valid_from")
        if self.review_after and self.valid_until and self.review_after > self.valid_until:
            raise ValueError("review_after cannot follow valid_until")
        return self


def parse_insight_result(value: dict) -> InsightResult | InsightResultV2:
    """Tagless v1 stays v1. Unknown explicit versions must fail, never downgrade."""
    model = InsightResultV2 if "schema_version" in value else InsightResult
    return model.model_validate(value)


class InsightOut(Schema):
    id: str
    company_id: str
    event_id: str
    versions: dict
    result: InsightResultV2 | InsightResult
    stale: bool = False
    stale_reasons: list[str] = []
    evaluated_at: datetime | None = None


class EventIn(Schema):
    event_id: str


class ChatIn(EventIn):
    company_id: str


class ChatOut(Schema):
    id: str
    company_id: str
    event_id: str


class ChatStateOut(ChatOut):
    event_title: str
    last_job: JobOut | None = None
    last_message_id: str | None = None
    last_client_message_id: str | None = None


class MessageIn(Schema):
    text: str = Field(min_length=1, max_length=10000)
    client_message_id: str | None = Field(
        default=None, min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    retry: bool = False


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


class FeedSnapshotItem(FeedItem):
    generation_status: Literal["ready", "not_requested", "failed", "deferred", "stale"]
    insight_id: str | None = None
    personalized_summary: StatementV2 | None = None
    mechanism: list[StatementV2] = Field(default_factory=list)
    impact_reason: StatementV2 | None = None
    time_horizon: TimeHorizon | None = None
    relevance_reason: StatementV2 | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    review_after: date | None = None
    unknowns: list[str] = Field(default_factory=list)
    impact_level: Literal["low", "medium", "high", "undetermined"] = "undetermined"
    relevance_status: Literal["active", "review_required", "expired", "undetermined"] = "undetermined"
    versions: dict
    error: dict | None = None

    @model_validator(mode="after")
    def ready_is_saved(self):
        if self.generation_status == "ready" and not self.insight_id:
            raise ValueError("ready preview requires a saved insight")
        if self.generation_status != "ready" and (
            self.insight_id
            or self.personalized_summary
            or self.mechanism
            or self.impact_reason
            or self.time_horizon
            or self.relevance_reason
            or self.valid_from
            or self.valid_until
            or self.review_after
            or self.unknowns
        ):
            raise ValueError("unready preview cannot expose a saved insight or summary")
        return self


class FeedSnapshotOut(Schema):
    schema_version: Literal["v2"] = "v2"
    snapshot_id: str
    generation_status: Literal["queued", "running", "ready", "partial", "failed", "deferred", "stale"]
    versions: dict
    stale: bool
    stale_reasons: list[str]
    ranking_version: str
    ranking_as_of: datetime
    ready_at: datetime | None
    job_id: str | None
    error: dict | None
    items: list[FeedSnapshotItem]
    total: int
    limit: int
    offset: int
    next_offset: int | None


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

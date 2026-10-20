from datetime import date

from pydantic import Field, field_validator, model_validator

from app.ai.schemas.claims import GroundedClaim
from app.ai.schemas.evidence import GroundedEvidence
from app.schemas import ChatResult, IngestResult, InsightResult, Schema, SummaryResult, UserFocus

MAX_SEARCH_ITEMS = 5


def _iso_date_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    return date.fromisoformat(value).isoformat()


class GroundedUserFocus(UserFocus):
    @model_validator(mode="after")
    def versioned_and_unique(self):
        if not self.version.strip():
            raise ValueError("version must not be blank")
        if len(set(self.topics)) != len(self.topics):
            raise ValueError("topics must not repeat")
        return self


class GroundedSummaryResult(SummaryResult):
    facts: list[GroundedClaim]

    @model_validator(mode="after")
    def has_summary_and_unique_facts(self):
        if not self.summary.strip():
            raise ValueError("summary must not be blank")
        ids = [fact.claim_id for fact in self.facts]
        if len(set(ids)) != len(ids):
            raise ValueError("fact claim_id values must be unique")
        return self


class OcrQuality(Schema):
    engine: str
    chunk_index: int = Field(ge=0)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)


class OcrChunk(Schema):
    page: int = Field(ge=1)
    text: str
    quality: OcrQuality

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk text must not be blank")
        return value


class GroundedIngestResult(IngestResult):
    chunks: list[OcrChunk]

    @field_validator("document_date")
    @classmethod
    def iso_date(cls, value: str | None) -> str | None:
        return _iso_date_or_none(value)

    @model_validator(mode="after")
    def has_chunks(self):
        if not self.chunks:
            raise ValueError("an ingested document must contain at least one chunk")
        return self


class BankSearchHit(Schema):
    chunk_id: str
    document_id: str
    version: str
    index_version: str
    page: int = Field(ge=1)
    document_date: str | None
    date_unknown: bool
    historical: bool = False
    text: str
    excerpt: str
    locator: dict
    score: float | None = None

    @model_validator(mode="after")
    def consistent_date_and_locator(self):
        if self.date_unknown != (self.document_date is None):
            raise ValueError("date_unknown must match document_date")
        if self.locator.get("page") != self.page:
            raise ValueError("locator.page must equal page")
        if not self.excerpt.strip():
            raise ValueError("excerpt must not be blank")
        return self


class BankSearchResult(Schema):
    items: list[BankSearchHit] = Field(max_length=MAX_SEARCH_ITEMS)
    query: str
    as_of: str
    empty_reason: str | None = None

    @field_validator("as_of")
    @classmethod
    def iso_date(cls, value: str) -> str:
        return date.fromisoformat(value).isoformat()

    @model_validator(mode="after")
    def empty_result_is_explained(self):
        if not self.items and not self.empty_reason:
            raise ValueError("an empty result requires empty_reason")
        return self


class GroundedInsightResult(InsightResult):
    facts: list[GroundedClaim]
    bank_view: list[GroundedClaim] | None
    ai_interpretation: list[GroundedClaim]
    risks: list[GroundedClaim]
    opportunities: list[GroundedClaim]
    actions: list[GroundedClaim]

    def claims(self) -> list[GroundedClaim]:
        sections = (
            self.facts,
            self.bank_view or [],
            self.ai_interpretation,
            self.risks,
            self.opportunities,
            self.actions,
        )
        return [claim for section in sections for claim in section]

    @model_validator(mode="after")
    def structurally_consistent(self):
        claims = self.claims()
        ids = [claim.claim_id for claim in claims]
        if len(set(ids)) != len(ids):
            raise ValueError("claim_id values must be unique across the whole insight")
        if self.bank_view is not None and not self.bank_view:
            raise ValueError("bank_view must be null when there is no bank evidence, not an empty list")
        if self.bank_view is None and not self.unknowns:
            raise ValueError("a missing bank_view must be explained in unknowns")
        if not self.facts and not self.unknowns:
            raise ValueError("an insight without facts must list unknowns")
        used = {ref for claim in claims for ref in claim.evidence_refs}
        if set(self.evidence_refs) != used:
            raise ValueError("evidence_refs must equal the union of claim evidence_refs")
        if not self.trace_id.strip():
            raise ValueError("trace_id must not be blank")
        return self


class ChatUsage(Schema):
    llm_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_rub: float = Field(default=0, ge=0)
    models: list[str] = []


class GroundedChatResult(ChatResult):
    usage: ChatUsage

    @model_validator(mode="after")
    def answer_is_supported_or_flagged(self):
        if not self.answer.strip():
            raise ValueError("answer must not be blank")
        if not self.evidence_refs and not self.unknowns:
            raise ValueError("an answer without evidence_refs must list unknowns")
        if not self.trace_id.strip():
            raise ValueError("trace_id must not be blank")
        return self


class AIEnvelopeBase(Schema):
    evidence: list[GroundedEvidence] = []
    trace: dict = {}

    @model_validator(mode="after")
    def evidence_ids_unique(self):
        ids = [item.id for item in self.evidence]
        if len(set(ids)) != len(ids):
            raise ValueError("envelope evidence ids must be unique")
        return self


class InsightEnvelope(AIEnvelopeBase):
    result: GroundedInsightResult

    @model_validator(mode="after")
    def bank_view_cites_only_bank_evidence(self):
        kinds = {item.id: item.kind for item in self.evidence}
        for claim in self.result.bank_view or []:
            wrong = [ref for ref in claim.evidence_refs if kinds.get(ref, "bank") != "bank"]
            if wrong:
                raise ValueError(f"bank_view claim {claim.claim_id} cites non-bank evidence {wrong}")
        return self


class ChatEnvelope(AIEnvelopeBase):
    result: GroundedChatResult

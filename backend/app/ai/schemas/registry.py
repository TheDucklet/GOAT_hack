from dataclasses import dataclass

from pydantic import BaseModel

from app.ai.schemas.errors import AIErrorCode
from app.ai.schemas.inputs import (
    AnswerChatInput,
    BuildInsightInput,
    DeriveUserFocusInput,
    IngestBankDocumentInput,
    SearchBankAnalyticsInput,
    SummarizeEventInput,
)
from app.ai.schemas.outputs import (
    BankSearchResult,
    ChatEnvelope,
    GroundedIngestResult,
    GroundedSummaryResult,
    GroundedUserFocus,
    InsightEnvelope,
)


@dataclass(frozen=True)
class FunctionContract:
    name: str
    input: type[BaseModel]
    output: type[BaseModel]
    errors: tuple[AIErrorCode, ...]


LLM_ERRORS: tuple[AIErrorCode, ...] = (
    "budget_exhausted",
    "model_not_allowed",
    "timeout",
    "rate_limited",
    "provider_unavailable",
    "invalid_json",
)

FUNCTION_CONTRACTS: dict[str, FunctionContract] = {
    contract.name: contract
    for contract in (
        FunctionContract(
            "derive_user_focus",
            DeriveUserFocusInput,
            GroundedUserFocus,
            LLM_ERRORS,
        ),
        FunctionContract(
            "summarize_event",
            SummarizeEventInput,
            GroundedSummaryResult,
            LLM_ERRORS,
        ),
        FunctionContract(
            "ingest_bank_document",
            IngestBankDocumentInput,
            GroundedIngestResult,
            ("invalid_ocr", "not_found", "model_not_allowed", "budget_exhausted", "timeout"),
        ),
        FunctionContract(
            "search_bank_analytics",
            SearchBankAnalyticsInput,
            BankSearchResult,
            ("forbidden", "ai_contract_error"),
        ),
        FunctionContract(
            "build_insight",
            BuildInsightInput,
            InsightEnvelope,
            LLM_ERRORS + ("forbidden", "ai_contract_error"),
        ),
        FunctionContract(
            "answer_chat",
            AnswerChatInput,
            ChatEnvelope,
            LLM_ERRORS + ("forbidden", "ai_contract_error"),
        ),
    )
}

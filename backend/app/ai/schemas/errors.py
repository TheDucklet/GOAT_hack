from typing import Literal

from app.schemas import Schema

AIErrorCode = Literal[
    "ai_unavailable",
    "ai_contract_error",
    "budget_exhausted",
    "model_not_allowed",
    "timeout",
    "rate_limited",
    "provider_unavailable",
    "invalid_json",
    "invalid_ocr",
    "not_found",
    "forbidden",
]

RETRYABLE_CODES: frozenset[str] = frozenset({"timeout", "rate_limited", "provider_unavailable"})


class AIFailure(Schema):
    code: AIErrorCode
    message: str
    retryable: bool
    request_id: str | None = None

    @classmethod
    def of(cls, code: AIErrorCode, message: str, request_id: str | None = None) -> "AIFailure":
        return cls(code=code, message=message, retryable=code in RETRYABLE_CODES, request_id=request_id)

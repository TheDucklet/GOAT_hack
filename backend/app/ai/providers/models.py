from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_MODEL_IDS: frozenset[str] = frozenset(
    {
        "google/gemma-4-26b-a4b-it",
        "z-ai/glm-5.3-flash",
        "qwen/qwen3.6-35b-a3b",
        "deepseek/deepseek-v4.1-flash",
        "qwen/qwen3-vl-30b-a3b-instruct",
        "moonshotai/kimi-k2.6",
    }
)

ReasoningEffort = Literal["none", "low", "medium", "high"]

CallStatus = Literal[
    "ok",
    "timeout",
    "rate_limited",
    "provider_unavailable",
    "invalid_json",
    "budget_exhausted",
    "model_not_allowed",
    "ai_unavailable",
]


class LLMInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    system: str = ""
    user: str = Field(min_length=1)
    image_data_urls: tuple[str, ...] = ()


class LLMRequest(BaseModel):
    request_id: str
    model_id: str
    system: str
    user: str
    image_data_urls: tuple[str, ...]
    max_tokens: int
    temperature: float
    json_mode: bool
    reasoning_effort: ReasoningEffort | None = None


class TransportResponse(BaseModel):
    status_code: int
    body: dict | None = None
    text: str = ""


class TokenUsage(BaseModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated: bool = False
    gateway_cost: float | None = None


class UsageRecord(BaseModel):
    request_id: str
    task: str
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    status: CallStatus
    cost_rub: float
    attempts: int
    estimated_tokens: bool
    cost_source: Literal["gateway", "tariff"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class LLMResult(BaseModel):
    request_id: str
    task: str
    model_id: str
    data: dict
    usage: UsageRecord

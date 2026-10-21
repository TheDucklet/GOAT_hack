from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.providers.models import ReasoningEffort

DEFAULT_TASK_MODELS: dict[str, str] = {
    "derive_user_focus": "google/gemma-4-26b-a4b-it",
    "summarize_event": "qwen/qwen3.6-35b-a3b",
    "build_insight": "qwen/qwen3.6-35b-a3b",
    "answer_chat": "qwen/qwen3.6-35b-a3b",
    "agent_check": "qwen/qwen3.6-35b-a3b",
    "ocr_vision": "qwen/qwen3-vl-30b-a3b-instruct",
}


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_", extra="ignore")

    llm_base_url: str = "https://changellenge.up.railway.app/v1"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=2)
    llm_retry_backoff_seconds: float = Field(default=1.0, ge=0)
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_reasoning_effort: ReasoningEffort | None = "none"
    llm_task_models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_TASK_MODELS))
    llm_tariffs_path: Path = Path(__file__).with_name("tariffs.json")
    llm_usage_log_path: Path | None = None


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()

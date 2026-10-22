"""Identity of the installed producer, excluding keys and user inputs."""

import hashlib
import os
from pathlib import Path

from app.ai.providers.settings import get_llm_settings


def producer_identity(settings=None):
    settings = settings or get_llm_settings()
    root = Path(__file__).resolve().parents[1]
    files = (
        "agent/prompts.py",
        "impact/prompts.py",
        "insights/prompts.py",
        "personalization/focus.py",
        "summarization/prompts.py",
        "chat/prompts.py",
    )
    return {
        "generation": os.environ.get("AI_GENERATION_VERSION", "1"),
        "prompts": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files},
        "gateway": settings.llm_base_url,
        "temperature": settings.llm_temperature,
        "reasoning": settings.llm_reasoning_effort,
    }

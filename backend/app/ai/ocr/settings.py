from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

OCR_PROMPT_VERSION = "ocr-8"
OCR_TASK = "ocr_vision"


class OcrSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_OCR_", extra="ignore")

    dpi: int = Field(default=300, ge=72, le=400)
    max_side_pixels: int = Field(default=3600, ge=800)
    max_tokens: int = Field(default=3500, ge=500)
    page_max_tokens: int = Field(default=4500, ge=500)
    tile_height_pixels: int = Field(default=1800, ge=400)
    request_timeout_seconds: float = Field(default=240, gt=0)
    min_page_chars: int = Field(default=3, ge=1)
    workers: int = Field(default=3, ge=1, le=6)
    page_attempts: int = Field(default=2, ge=1, le=3)
    cache_dir: Path = Path("storage/ai-cache/ocr")


@lru_cache
def get_ocr_settings() -> OcrSettings:
    return OcrSettings()

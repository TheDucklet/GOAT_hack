from dataclasses import dataclass

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BOUNDARY_SEARCH_SHARE = 0.6


class ChunkSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_RAG_", extra="ignore")

    chunk_chars: int = Field(default=1200, ge=200)
    overlap_chars: int = Field(default=200, ge=0)


@dataclass(frozen=True)
class TextChunk:
    index: int
    start: int
    end: int
    text: str


def split_text(text: str, chunk_chars: int, overlap_chars: int) -> list[TextChunk]:
    if overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars must be smaller than chunk_chars")
    chunks: list[TextChunk] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            end = _cut_position(text, start, end, chunk_chars)
        piece = text[start:end].strip()
        if piece:
            chunks.append(TextChunk(len(chunks), start, end, piece))
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def _cut_position(text: str, start: int, end: int, chunk_chars: int) -> int:
    floor = start + int(chunk_chars * BOUNDARY_SEARCH_SHARE)
    for separator in ("\n", ". ", " "):
        position = text.rfind(separator, floor, end)
        if position != -1:
            return position + len(separator)
    return end

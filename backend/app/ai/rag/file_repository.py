import json
from pathlib import Path

from app.ai.rag.search import stem

MAX_RESULTS = 20


class FileRepository:
    def __init__(self, path: Path):
        self._chunks: list[dict] = json.loads(path.read_text(encoding="utf-8"))

    def search_chunks(self, query: str, as_of: str, limit: int = 5) -> list[dict]:
        words = [stem(word) for word in query.lower().split() if word]
        found = []
        for chunk in self._chunks:
            published = chunk["document_date"]
            if published is not None and published > as_of:
                continue
            text = chunk["text"].lower()
            if words and all(word in text for word in words):
                found.append((sum(text.count(word) for word in words), chunk))
        found.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [
            {**chunk, "date_unknown": chunk["document_date"] is None}
            for _, chunk in found[: max(1, min(limit, MAX_RESULTS))]
        ]

import json
from collections.abc import Callable
from pathlib import Path

from app.ai.rag.search import search_bank_analytics
from app.integrations.ai import AIError

MAX_RESULTS = 5
MAX_QUERY_CHARS = 1000

SearchFunction = Callable[[str, str, int], dict]


def repository_search(repository) -> SearchFunction:
    return lambda query, as_of, limit: search_bank_analytics(query, as_of, limit, repository)


class SearchSnapshot:
    def __init__(self, path: Path):
        self._path = path
        self._records: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @staticmethod
    def key(query: str, as_of: str, limit: int) -> str:
        return json.dumps([query, as_of, limit], ensure_ascii=False)

    def recording(self, search: SearchFunction) -> SearchFunction:
        def record(query: str, as_of: str, limit: int) -> dict:
            result = search(query, as_of, limit)
            self._records[self.key(query, as_of, limit)] = result
            return result

        return record

    def replay(self, query: str, as_of: str, limit: int) -> dict:
        key = self.key(query, as_of, limit)
        if key not in self._records:
            raise AIError("not_found", "Для запроса нет сохранённого результата поиска, обновите снимок")
        return self._records[key]

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )


class LocalTools:
    def __init__(self, company_context: dict, event: dict, search: SearchFunction):
        self._company_context = company_context
        self._event = event
        self._search = search

    def get_company_context(self, company_id: str | None = None) -> dict:
        if company_id is not None and company_id != self._company_context["company_id"]:
            raise AIError("forbidden", "Инструмент ограничен выбранной компанией")
        return self._company_context

    def get_event(self) -> dict:
        return self._event

    def search_bank_analytics(self, query: str, as_of: str, limit: int = MAX_RESULTS) -> dict:
        return self._search(query[:MAX_QUERY_CHARS], as_of, max(1, min(limit, MAX_RESULTS)))

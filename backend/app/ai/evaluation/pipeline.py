import json
from pathlib import Path

from app.ai.agent.runner import run_agent
from app.ai.insights.build import SEARCH_LIMIT
from app.ai.insights.local_tools import LocalTools, repository_search
from app.ai.personalization.focus import derive_user_focus
from app.ai.rag.file_repository import FileRepository
from app.ai.summarization.summarize import summarize_event

DEFAULT_FIXTURES = Path("../docs/ai/fixtures")
DEFAULT_INPUTS = Path("../docs/quality/fixtures/acceptance-inputs.json")


class Workspace:
    def __init__(self, fixtures: Path = DEFAULT_FIXTURES, inputs: Path = DEFAULT_INPUTS):
        self.fixtures = fixtures
        self.chunks_path = fixtures / "bank-chunks.json"
        self.inputs = json.loads(inputs.read_text(encoding="utf-8"))
        self.companies = {
            item["company_id"]: item
            for item in json.loads((fixtures / "companies.json").read_text(encoding="utf-8"))
        } | self.inputs["companies"]
        self.repository = FileRepository(self.chunks_path)
        self.search = repository_search(self.repository)

    def raw_event(self, name: str) -> dict:
        return self.inputs["events"][name]

    def position(self, name: str) -> dict:
        return self.inputs["positions"][name]


class SearchLog:
    def __init__(self, search, suppressed: int = 0):
        self._search = search
        self._suppressed = suppressed
        self.calls: list[dict] = []

    def __call__(self, query: str, as_of: str, limit: int) -> dict:
        hidden = len(self.calls) < self._suppressed
        if hidden:
            found = {
                "items": [],
                "query": query,
                "as_of": as_of,
                "empty_reason": "результат скрыт в сценарии отсутствия первого evidence",
            }
        else:
            found = self._search(query, as_of, limit)
        self.calls.append(
            {
                "query": query,
                "as_of": as_of,
                "limit": limit,
                "suppressed": hidden,
                "chunk_ids": [item["chunk_id"] for item in found.get("items", [])],
            }
        )
        return found


def summarized(raw_event: dict) -> tuple[dict, dict]:
    summary = summarize_event(raw_event)
    event = {
        **raw_event,
        "summary": summary["summary"],
        "facts": summary["facts"],
        "topics": summary["topics"],
    }
    return event, summary


def focus_of(position: dict) -> dict:
    return derive_user_focus(position["position_text"], position["interests"])


def card_for(
    workspace: Workspace, company: dict, focus: dict, event: dict, suppressed: int = 0
) -> tuple[dict, list[dict]]:
    log = SearchLog(workspace.search, suppressed)
    tools = LocalTools(company, event, log)
    envelope = run_agent(company, focus, event, tools)
    return envelope, log.calls


__all__ = ["SEARCH_LIMIT", "SearchLog", "Workspace", "card_for", "focus_of", "summarized"]

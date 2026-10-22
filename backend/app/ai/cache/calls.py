from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.agent.prompts import AGENT_PROMPT_VERSION
from app.ai.cache.identity import producer_identity
from app.ai.cache.keys import digest_of, focus_hash, make_key
from app.ai.cache.service import ResultCache
from app.ai.cache.store import FileStore
from app.ai.impact import build_impact_insight
from app.ai.impact.prompts import IMPACT_PROMPT_VERSION
from app.ai.insights.prompts import INSIGHT_PROMPT_VERSION
from app.ai.personalization.focus import FOCUS_PROMPT_VERSION, derive_user_focus
from app.ai.providers import LLMSettings, get_llm_settings
from app.ai.summarization.prompts import SUMMARY_PROMPT_VERSION
from app.ai.summarization.summarize import summarize_event
from app.ai.validation import VALIDATION_VERSION
from app.insight_versions import contract_versions

SUMMARY_TASKS = ("summarize_event", "select_industries")
FOCUS_TASKS = ("derive_user_focus",)
INSIGHT_TASKS = ("agent_plan", "agent_query", "agent_check", "build_insight", "build_impact")


class CacheSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AI_CACHE_", extra="ignore")

    dir: Path | None = None
    enabled: bool = True


@lru_cache
def get_result_cache() -> ResultCache:
    settings = CacheSettings()
    return ResultCache(FileStore(settings.dir) if settings.dir else None, settings.enabled)


def model_versions(tasks: tuple[str, ...], settings: LLMSettings | None = None) -> dict[str, str]:
    models = (settings or get_llm_settings()).llm_task_models
    return {task: models.get(task, "") for task in tasks}


def corpus_version_of(tools) -> str | None:
    provider = getattr(tools, "corpus_version", None)
    if not callable(provider):
        return None
    version = provider()
    return str(version) if version else None


def cached_summarize_event(
    event: dict, cache: ResultCache | None = None, settings: LLMSettings | None = None
) -> dict:
    cache = cache or get_result_cache()
    key = make_key(
        "summary",
        producer=producer_identity(settings),
        event_id=event.get("id"),
        event_version=event.get("version"),
        input_hash=digest_of(event),
        prompt_version=SUMMARY_PROMPT_VERSION,
        models=model_versions(SUMMARY_TASKS, settings),
    )
    return cache.fetch(key, lambda: summarize_event(event))[0]


def cached_derive_user_focus(
    position_text: str,
    interests: list[str],
    cache: ResultCache | None = None,
    settings: LLMSettings | None = None,
) -> dict:
    cache = cache or get_result_cache()
    key = make_key(
        "focus",
        producer=producer_identity(settings),
        input_hash=digest_of([" ".join(position_text.split()), sorted(interests)]),
        prompt_version=FOCUS_PROMPT_VERSION,
        models=model_versions(FOCUS_TASKS, settings),
    )
    return cache.fetch(key, lambda: derive_user_focus(position_text, interests))[0]


def cached_build_insight(
    company_context: dict,
    user_focus: dict,
    event: dict,
    tools,
    cache: ResultCache | None = None,
    settings: LLMSettings | None = None,
) -> dict:
    cache = cache or get_result_cache()

    def compute() -> dict:
        return build_impact_insight(company_context, user_focus, event, tools)

    corpus = corpus_version_of(tools)
    if corpus is None:
        return cache.bypass("insight", compute)
    key = make_key(
        "insight",
        producer=producer_identity(settings),
        contract_versions=contract_versions(company_context.get("data_semantics_version")),
        company_id=company_context.get("company_id"),
        profile_version=company_context.get("profile_version"),
        event_id=event.get("id"),
        event_version=event.get("version"),
        focus_hash=focus_hash(user_focus),
        corpus_version=corpus,
        prompt_version={
            "insight": INSIGHT_PROMPT_VERSION,
            "agent": AGENT_PROMPT_VERSION,
            "impact": IMPACT_PROMPT_VERSION,
            "validation": VALIDATION_VERSION,
        },
        model_version=model_versions(INSIGHT_TASKS, settings),
    )
    envelope, hit = cache.fetch(key, compute)
    if hit:
        envelope["trace"] = {**envelope["trace"], "cache": {"hit": True, "key": key.digest}}
        if "trace_id" in envelope["result"]:
            envelope["result"]["trace_id"] = uuid4().hex
    return envelope

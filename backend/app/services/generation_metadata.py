import hashlib
import json

from app.config import get_settings


def generation_versions() -> dict[str, str]:
    """Read producer metadata only. No provider or generation function is called."""
    settings = get_settings()
    prompts, models = {}, {}
    if settings.ai_module == "app.ai.bridge":
        from app.ai.agent.prompts import AGENT_PROMPT_VERSION
        from app.ai.cache.identity import producer_identity
        from app.ai.impact.prompts import IMPACT_PROMPT_VERSION
        from app.ai.insights.prompts import INSIGHT_PROMPT_VERSION
        from app.ai.personalization.focus import FOCUS_PROMPT_VERSION
        from app.ai.providers.settings import get_llm_settings
        from app.ai.validation import VALIDATION_VERSION

        runtime = get_llm_settings()
        prompts = dict(
            installed=producer_identity(),
            agent=AGENT_PROMPT_VERSION,
            impact=IMPACT_PROMPT_VERSION,
            insight=INSIGHT_PROMPT_VERSION,
            focus=FOCUS_PROMPT_VERSION,
            validation=VALIDATION_VERSION,
        )
        models = dict(
            tasks=runtime.llm_task_models,
            temperature=runtime.llm_temperature,
            reasoning=runtime.llm_reasoning_effort,
            gateway=runtime.llm_base_url,
        )

    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    namespace = [settings.ai_module, settings.ai_generation_version]
    return {"prompt": digest([namespace, prompts]), "model": digest([namespace, models])}

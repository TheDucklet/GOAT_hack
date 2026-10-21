import math
from functools import lru_cache
from pathlib import Path

from app.ai.budget import BudgetConfig, BudgetLedger
from app.ai.providers.models import LLMRequest
from app.ai.providers.settings import LLMSettings
from app.ai.providers.tariffs import TariffTable


def estimate_cost_rub(tariffs: TariffTable, config: BudgetConfig, request: LLMRequest) -> float:
    characters = len(request.system) + len(request.user)
    input_tokens = math.ceil(characters / config.chars_per_token)
    input_tokens += len(request.image_data_urls) * config.image_tokens
    return tariffs.cost_rub(request.model_id, input_tokens, request.max_tokens)


@lru_cache(maxsize=8)
def shared_ledger(limits_path: Path, ledger_path: Path | None, daily_limit_rub: float | None) -> BudgetLedger:
    config = BudgetConfig.load(limits_path)
    if daily_limit_rub is not None:
        config = config.model_copy(update={"daily_limit_rub": daily_limit_rub})
    return BudgetLedger(config, ledger_path)


def default_ledger(settings: LLMSettings) -> BudgetLedger:
    return shared_ledger(
        settings.llm_budget_limits_path, settings.llm_budget_ledger_path, settings.llm_daily_limit_rub
    )

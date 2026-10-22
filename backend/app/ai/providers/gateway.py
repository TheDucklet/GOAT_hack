import json
import re
import time
from collections.abc import Callable
from functools import lru_cache
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from app.ai.budget import BudgetExhausted, BudgetLedger, Reservation
from app.ai.providers.budgeting import default_ledger, estimate_cost_rub
from app.ai.providers.models import (
    ALLOWED_MODEL_IDS,
    CallStatus,
    LLMInput,
    LLMRequest,
    LLMResult,
    ReasoningEffort,
    TokenUsage,
    TransportResponse,
    UsageRecord,
)
from app.ai.providers.settings import LLMSettings, get_llm_settings
from app.ai.providers.tariffs import TariffTable
from app.ai.providers.transport import HttpxTransport, Transport, TransportFailure
from app.ai.providers.usage import LoggingUsageSink, UsageSink
from app.ai.schemas.errors import AIErrorCode
from app.integrations.ai import AIError

RETRYABLE_STATUSES: frozenset[str] = frozenset({"timeout", "rate_limited", "provider_unavailable"})

FAILURE_MESSAGES: dict[str, str] = {
    "timeout": "Модель не ответила за отведённое время, повторите запрос позже",
    "rate_limited": "Провайдер ограничил частоту запросов, повторите запрос позже",
    "provider_unavailable": "Провайдер модели временно недоступен, повторите запрос позже",
    "budget_exhausted": "Дневной лимит на обращения к модели исчерпан, дождитесь сброса в 3:00 МСК",
    "ai_unavailable": "Доступ к модели не настроен или отклонён, проверьте ключ и адрес в .env",
    "ai_contract_error": "Провайдер отклонил запрос, проверьте модель и параметры вызова",
    "invalid_json": "Модель вернула ответ, который не удалось разобрать как JSON по схеме",
    "model_not_allowed": "Модель для задачи не входит в список разрешённых кейсом, проверьте настройки",
}

THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class LLMError(AIError):
    def __init__(self, code: AIErrorCode, request_id: str):
        super().__init__(code, FAILURE_MESSAGES[code])
        self.request_id = request_id
        self.retryable = code in RETRYABLE_STATUSES


def parse_json_object(text: str) -> dict:
    cleaned = CODE_FENCE.sub("", THINK_BLOCK.sub("", text).strip()).strip()
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def classify_failure(response: TransportResponse) -> AIErrorCode | None:
    status, text = response.status_code, response.text.lower()
    if "budget" in text and "exceed" in text:
        return "budget_exhausted"
    if status == 429:
        return "rate_limited"
    if status in (408, 504):
        return "timeout"
    if status >= 500:
        return "provider_unavailable"
    if status in (401, 403):
        return "ai_unavailable"
    if status >= 400:
        return "ai_contract_error"
    return None


def extract_content(response: TransportResponse) -> str:
    body = response.body or {}
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("response has no message content") from error
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise ValueError("response content is empty")
    return content


def read_usage(response: TransportResponse, content: str = "") -> TokenUsage:
    raw = (response.body or {}).get("usage") or {}
    cost = raw.get("cost")
    gateway_cost = float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else None
    if "prompt_tokens" in raw and "completion_tokens" in raw:
        return TokenUsage(
            input_tokens=int(raw["prompt_tokens"]),
            output_tokens=int(raw["completion_tokens"]),
            gateway_cost=gateway_cost,
        )
    output = max(1, len(content) // 3) if content else 0
    return TokenUsage(output_tokens=output, estimated=True, gateway_cost=gateway_cost)


@lru_cache(maxsize=4)
def shared_transport(base_url: str, api_key: str, timeout_seconds: float) -> HttpxTransport:
    return HttpxTransport(base_url, api_key, timeout_seconds)


def default_transport(settings: LLMSettings) -> Transport:
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        raise LLMError("ai_unavailable", "-")
    return shared_transport(
        settings.llm_base_url, settings.llm_api_key.get_secret_value(), settings.llm_timeout_seconds
    )


def call_llm(
    task: str,
    input: LLMInput,
    max_tokens: int,
    *,
    response_model: type[BaseModel] | None = None,
    json_mode: bool = True,
    reasoning_effort: ReasoningEffort | None = None,
    timeout_seconds: float | None = None,
    temperature: float | None = None,
    frequency_penalty: float | None = None,
    settings: LLMSettings | None = None,
    transport: Transport | None = None,
    usage_sink: UsageSink | None = None,
    tariffs: TariffTable | None = None,
    budget: BudgetLedger | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> LLMResult:
    settings = settings or get_llm_settings()
    tariffs = tariffs or TariffTable.load(settings.llm_tariffs_path)
    usage_sink = usage_sink or LoggingUsageSink(settings.llm_usage_log_path)
    budget = budget or default_ledger(settings)
    reservation: Reservation | None = None
    request_id = uuid4().hex
    started = time.monotonic()
    model_id = settings.llm_task_models.get(task, "")
    attempts = 0
    prior_cost = 0.0

    def finish(status: CallStatus, tokens: TokenUsage) -> UsageRecord:
        current_cost = (
            tokens.gateway_cost
            if tokens.gateway_cost is not None
            else tariffs.cost_rub(model_id, tokens.input_tokens, tokens.output_tokens)
        )
        record = UsageRecord(
            request_id=request_id,
            task=task,
            model_id=model_id,
            input_tokens=tokens.input_tokens,
            output_tokens=tokens.output_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            status=status,
            cost_rub=current_cost + prior_cost,
            attempts=attempts,
            estimated_tokens=tokens.estimated or prior_cost > 0,
            cost_source="tariff" if tokens.gateway_cost is None else "gateway",
        )
        usage_sink.record(record)
        if reservation is not None:
            budget.settle(reservation, current_cost, task, model_id, status)
        return record

    def fail(code: AIErrorCode, tokens: TokenUsage | None = None) -> LLMError:
        finish(code, tokens or TokenUsage())
        return LLMError(code, request_id)

    if model_id not in ALLOWED_MODEL_IDS:
        raise fail("model_not_allowed")
    if max_tokens < 1:
        raise fail("ai_contract_error")
    try:
        transport = transport or default_transport(settings)
    except LLMError as error:
        raise fail(error.code) from None

    request = LLMRequest(
        request_id=request_id,
        model_id=model_id,
        system=input.system,
        user=input.user,
        image_data_urls=input.image_data_urls,
        max_tokens=max_tokens,
        temperature=settings.llm_temperature if temperature is None else temperature,
        json_mode=json_mode,
        reasoning_effort=reasoning_effort or settings.llm_reasoning_effort,
        timeout_seconds=timeout_seconds or settings.llm_timeout_seconds,
        frequency_penalty=frequency_penalty,
    )
    try:
        reservation = budget.reserve(request_id, estimate_cost_rub(tariffs, budget.config, request))
    except BudgetExhausted:
        raise fail("budget_exhausted") from None
    last_failure: AIErrorCode = "provider_unavailable"
    for attempt in range(settings.llm_max_retries + 1):
        if attempt:
            sleep(settings.llm_retry_backoff_seconds * 2 ** (attempt - 1))
            try:
                reservation = budget.reserve(
                    f"{request_id}.{attempt}", estimate_cost_rub(tariffs, budget.config, request)
                )
            except BudgetExhausted:
                raise fail("budget_exhausted") from None
        attempts = attempt + 1
        try:
            response = transport.send(request)
        except TransportFailure as failure:
            last_failure = "timeout" if failure.kind == "timeout" else "provider_unavailable"
            # A timed-out request may have been billed remotely. Keep its worst-case cost.
            prior_cost += reservation.amount_rub
            budget.settle(reservation, reservation.amount_rub, task, model_id, last_failure)
            reservation = None
            continue
        failure_code = classify_failure(response)
        if failure_code in RETRYABLE_STATUSES:
            last_failure = failure_code
            tokens = read_usage(response)
            cost = (
                tokens.gateway_cost
                if tokens.gateway_cost is not None
                else tariffs.cost_rub(model_id, tokens.input_tokens, tokens.output_tokens)
            )
            if failure_code != "rate_limited" and cost == 0:
                cost = reservation.amount_rub
            prior_cost += cost
            budget.settle(reservation, cost, task, model_id, failure_code)
            reservation = None
            continue
        if failure_code:
            if failure_code == "budget_exhausted":
                budget.mark_exhausted()
            raise fail(failure_code)
        try:
            content = extract_content(response)
            tokens = read_usage(response, content)
            data = parse_json_object(content)
            if response_model is not None:
                data = response_model.model_validate(data).model_dump(mode="json")
        except (ValueError, ValidationError):
            raise fail("invalid_json", read_usage(response)) from None
        return LLMResult(
            request_id=request_id,
            task=task,
            model_id=model_id,
            data=data,
            usage=finish("ok", tokens),
        )
    raise fail(last_failure)

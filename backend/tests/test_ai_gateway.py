import pytest
from pydantic import BaseModel

from app.ai.providers import (
    ALLOWED_MODEL_IDS,
    LLMError,
    LLMInput,
    LLMSettings,
    MemoryUsageSink,
    TariffTable,
    call_llm,
    parse_json_object,
)
from app.ai.providers.models import LLMRequest
from app.ai.providers.settings import DEFAULT_TASK_MODELS
from app.ai.providers.testing import ScriptedTransport, completion, http_error, json_completion
from app.ai.providers.transport import TransportFailure, build_payload

TARIFFS = TariffTable(1_000_000, {"qwen/qwen3.6-35b-a3b": {"input": 25, "output": 100}})
PROMPT = LLMInput(system="Отвечай JSON.", user="Секретный клиентский запрос")


def settings(**overrides):
    values = {"llm_api_key": "sk-test", "llm_retry_backoff_seconds": 0, **overrides}
    return LLMSettings(_env_file=None, **values)


def run(transport, sink=None, **kwargs):
    sink = sink if sink is not None else MemoryUsageSink()
    options = {
        "settings": kwargs.pop("settings", settings()),
        "transport": transport,
        "usage_sink": sink,
        "tariffs": TARIFFS,
        "sleep": lambda seconds: None,
    }
    return call_llm(
        kwargs.pop("task", "summarize_event"), PROMPT, kwargs.pop("max_tokens", 500), **options, **kwargs
    ), sink


def test_default_task_models_are_all_allowed():
    assert set(DEFAULT_TASK_MODELS.values()) <= ALLOWED_MODEL_IDS


def test_successful_call_returns_json_and_usage_record():
    transport = ScriptedTransport(json_completion({"answer": 1}, 1000, 200))
    result, sink = run(transport)
    assert result.data == {"answer": 1}
    assert result.model_id == "qwen/qwen3.6-35b-a3b"
    assert result.request_id and result.usage.request_id == result.request_id
    assert (result.usage.input_tokens, result.usage.output_tokens) == (1000, 200)
    assert result.usage.cost_rub == pytest.approx(0.045)
    assert sink.records == [result.usage]
    assert transport.requests[0].request_id == result.request_id


def test_unlisted_model_is_rejected_before_any_network_call():
    transport = ScriptedTransport()
    sink = MemoryUsageSink()
    bad = settings(llm_task_models={"summarize_event": "openai/gpt-4o"})
    with pytest.raises(LLMError) as raised:
        run(transport, sink, settings=bad)
    assert raised.value.code == "model_not_allowed"
    assert transport.calls == 0
    assert sink.records[0].status == "model_not_allowed"


def test_task_without_configured_model_is_rejected_before_any_network_call():
    transport = ScriptedTransport()
    with pytest.raises(LLMError) as raised:
        run(transport, task="unknown_task")
    assert raised.value.code == "model_not_allowed"
    assert transport.calls == 0


def test_transient_error_is_retried_twice_and_then_succeeds():
    transport = ScriptedTransport(TransportFailure("timeout"), http_error(503), json_completion({"ok": True}))
    result, _ = run(transport)
    assert transport.calls == 3
    assert result.usage.attempts == 3


def test_exhausted_retries_raise_typed_error_without_fake_answer():
    transport = ScriptedTransport(
        TransportFailure("timeout"), TransportFailure("timeout"), TransportFailure("timeout")
    )
    sink = MemoryUsageSink()
    with pytest.raises(LLMError) as raised:
        run(transport, sink)
    assert raised.value.code == "timeout"
    assert raised.value.retryable
    assert transport.calls == 3
    assert sink.records[0].status == "timeout"
    assert sink.records[0].attempts == 3


def test_third_retry_is_never_made():
    transport = ScriptedTransport(http_error(500), http_error(500), http_error(500), json_completion({}))
    with pytest.raises(LLMError):
        run(transport)
    assert transport.calls == 3


def test_rate_limit_is_retryable_and_reported_as_such():
    transport = ScriptedTransport(http_error(429), http_error(429), http_error(429))
    with pytest.raises(LLMError) as raised:
        run(transport)
    assert raised.value.code == "rate_limited"


def test_exceeded_budget_is_not_retried():
    transport = ScriptedTransport(
        http_error(400, '{"error": {"message": "Budget has been exceeded! Current cost: 500"}}')
    )
    with pytest.raises(LLMError) as raised:
        run(transport)
    assert raised.value.code == "budget_exhausted"
    assert not raised.value.retryable
    assert transport.calls == 1


def test_authorization_error_is_not_retried():
    transport = ScriptedTransport(http_error(401, "invalid key"))
    with pytest.raises(LLMError) as raised:
        run(transport)
    assert raised.value.code == "ai_unavailable"
    assert transport.calls == 1


def test_invalid_json_is_reported_without_retry_and_keeps_token_usage():
    transport = ScriptedTransport(completion("это не JSON", 300, 20))
    sink = MemoryUsageSink()
    with pytest.raises(LLMError) as raised:
        run(transport, sink)
    assert raised.value.code == "invalid_json"
    assert transport.calls == 1
    assert sink.records[0].input_tokens == 300


def test_json_wrapped_in_fence_and_reasoning_block_is_accepted():
    text = '<think>рассуждение</think>\n```json\n{"a": 2}\n```'
    result, _ = run(ScriptedTransport(completion(text)))
    assert result.data == {"a": 2}


def test_json_array_is_rejected():
    with pytest.raises(LLMError) as raised:
        run(ScriptedTransport(completion("[1, 2]")))
    assert raised.value.code == "invalid_json"


def test_response_model_rejects_wrong_shape():
    class Answer(BaseModel):
        value: int

    with pytest.raises(LLMError) as raised:
        run(ScriptedTransport(json_completion({"value": "text"})), response_model=Answer)
    assert raised.value.code == "invalid_json"


def test_response_model_normalizes_data():
    class Answer(BaseModel):
        value: int = 7

    result, _ = run(ScriptedTransport(json_completion({})), response_model=Answer)
    assert result.data == {"value": 7}


def test_missing_api_key_gives_typed_error_without_network():
    with pytest.raises(LLMError) as raised:
        call_llm(
            "summarize_event",
            PROMPT,
            100,
            settings=LLMSettings(_env_file=None, llm_api_key=None),
            usage_sink=MemoryUsageSink(),
            tariffs=TARIFFS,
        )
    assert raised.value.code == "ai_unavailable"


def test_error_text_and_usage_record_do_not_contain_key_or_prompt():
    transport = ScriptedTransport(http_error(401, "key sk-test rejected"))
    sink = MemoryUsageSink()
    with pytest.raises(LLMError) as raised:
        run(transport, sink)
    dumped = raised.value.message + sink.records[0].model_dump_json()
    assert "sk-test" not in dumped
    assert "Секретный" not in dumped


def test_payload_requests_json_and_includes_images():
    request = LLMRequest(
        request_id="r",
        model_id="qwen/qwen3-vl-30b-a3b-instruct",
        system="s",
        user="u",
        image_data_urls=("data:image/png;base64,AAAA",),
        max_tokens=10,
        temperature=0,
        json_mode=True,
    )
    payload = build_payload(request)
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png")


def test_retry_count_is_bounded_by_two_in_settings():
    with pytest.raises(ValueError):
        settings(llm_max_retries=3)


def test_parse_json_object_extracts_object_from_surrounding_text():
    assert parse_json_object('Вот ответ: {"x": 1} готово') == {"x": 1}


def test_usage_is_estimated_when_provider_omits_it():
    body = {"choices": [{"message": {"content": '{"a": 1}'}}]}
    from app.ai.providers.models import TransportResponse

    result, _ = run(ScriptedTransport(TransportResponse(status_code=200, body=body)))
    assert result.usage.estimated_tokens
    assert result.usage.output_tokens >= 1

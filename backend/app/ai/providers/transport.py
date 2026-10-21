from typing import Protocol

import httpx

from app.ai.providers.models import LLMRequest, TransportResponse


class TransportFailure(Exception):
    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class Transport(Protocol):
    def send(self, request: LLMRequest) -> TransportResponse: ...


def build_payload(request: LLMRequest) -> dict:
    content: str | list[dict] = request.user
    if request.image_data_urls:
        content = [{"type": "text", "text": request.user}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in request.image_data_urls
        ]
    messages = ([{"role": "system", "content": request.system}] if request.system else []) + [
        {"role": "user", "content": content}
    ]
    payload = {
        "model": request.model_id,
        "messages": messages,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    if request.reasoning_effort is not None:
        payload["reasoning_effort"] = request.reasoning_effort
    if request.json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


class HttpxTransport:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: float):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def send(self, request: LLMRequest) -> TransportResponse:
        try:
            response = self._client.post(
                "/chat/completions",
                json=build_payload(request),
                headers={"X-Request-ID": request.request_id},
            )
        except httpx.TimeoutException as error:
            raise TransportFailure("timeout") from error
        except httpx.TransportError as error:
            raise TransportFailure("provider_unavailable") from error
        try:
            body = response.json()
        except ValueError:
            body = None
        return TransportResponse(
            status_code=response.status_code,
            body=body if isinstance(body, dict) else None,
            text=response.text[:2000],
        )

    def close(self) -> None:
        self._client.close()

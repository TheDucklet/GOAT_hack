import json

from app.ai.providers.models import LLMRequest, TransportResponse
from app.ai.providers.transport import TransportFailure


def completion(content: str, input_tokens: int = 100, output_tokens: int = 50) -> TransportResponse:
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
    }
    return TransportResponse(status_code=200, body=body, text=json.dumps(body, ensure_ascii=False))


def json_completion(payload: dict, input_tokens: int = 100, output_tokens: int = 50) -> TransportResponse:
    return completion(json.dumps(payload, ensure_ascii=False), input_tokens, output_tokens)


def http_error(status_code: int, text: str = "") -> TransportResponse:
    return TransportResponse(status_code=status_code, body=None, text=text)


class ScriptedTransport:
    def __init__(self, *script: TransportResponse | TransportFailure):
        self._script = list(script)
        self.requests: list[LLMRequest] = []

    def send(self, request: LLMRequest) -> TransportResponse:
        self.requests.append(request)
        if not self._script:
            raise AssertionError("ScriptedTransport script is exhausted")
        step = self._script.pop(0)
        if isinstance(step, TransportFailure):
            raise step
        return step

    @property
    def calls(self) -> int:
        return len(self.requests)

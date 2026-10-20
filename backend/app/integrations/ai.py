"""Backend integration boundary. Fedor supplies the configured Python module."""

import importlib

from app.config import get_settings


class AIError(Exception):
    def __init__(self, code="ai_unavailable", message="AI-модуль ещё не подключён"):
        self.code, self.message = code, message


def call_ai(function: str, **kwargs) -> dict:
    module_name = get_settings().ai_module
    if not module_name:
        raise AIError()
    module = importlib.import_module(module_name)
    function_impl = getattr(module, function, None)
    if not function_impl:
        raise AIError("ai_contract_error", "AI-модуль не реализует необходимую функцию")
    result = function_impl(**kwargs)
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    if not isinstance(result, dict):
        raise AIError("ai_contract_error", "AI-модуль вернул результат неверного формата")
    return result

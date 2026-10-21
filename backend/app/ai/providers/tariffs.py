import json
from pathlib import Path


class TariffTable:
    def __init__(self, per_tokens: int, models: dict[str, dict[str, float]]):
        self._per_tokens = per_tokens
        self._models = models

    @classmethod
    def load(cls, path: Path) -> "TariffTable":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(int(raw["per_tokens"]), raw["models"])

    def cost_rub(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        rate = self._models.get(model_id)
        if rate is None:
            return 0.0
        total = input_tokens * rate["input"] + output_tokens * rate["output"]
        return round(total / self._per_tokens, 6)

    def knows(self, model_id: str) -> bool:
        return model_id in self._models

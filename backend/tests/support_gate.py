import json
from types import SimpleNamespace

from app.ai.gate import verify as gate_verify


class Verifier:
    def __init__(self, verdicts=None, error=None, omit=()):
        self.verdicts = verdicts or {}
        self.error = error
        self.omit = set(omit)
        self.payloads = []

    def __call__(self, task, request, max_tokens, **options):
        if self.error:
            raise self.error
        payload = json.loads(request.user)
        self.payloads.append(payload)
        position = len(self.payloads) - 1
        rows = []
        for item in payload["claims"]:
            if item["id"] in self.omit:
                continue
            verdict = self.verdicts.get((position, item["id"])) or self.verdicts.get(item["id"], "supported")
            rows.append({"id": item["id"], "verdict": verdict, "reason": f"{verdict} в тесте"})
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cost_rub=0.01)
        return SimpleNamespace(
            data={"verdicts": rows}, request_id=f"r{position}", model_id="verifier-model", usage=usage
        )


def install(monkeypatch, verifier=None):
    verifier = verifier or Verifier()
    monkeypatch.setattr(gate_verify, "call_llm", verifier)
    return verifier

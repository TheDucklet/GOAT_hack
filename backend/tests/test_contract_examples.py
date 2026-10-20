import json
from pathlib import Path

from app import schemas


def test_published_examples_validate_against_current_schemas():
    path = Path(__file__).resolve().parents[2] / "docs/contracts/examples.json"
    examples = json.loads(path.read_text(encoding="utf-8"))
    assert {e["name"] for e in examples} >= {"insight_with_bank", "insight_without_bank", "insufficient_data"}
    for example in examples:
        getattr(schemas, example["schema"]).model_validate(example["data"])

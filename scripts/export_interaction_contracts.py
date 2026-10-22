"""Generate the A16 handoff examples from the canonical DTOs."""

import argparse
import json
from pathlib import Path

from app.schemas import (
    DemoActionIn,
    DemoActionOut,
    DismissalIn,
    DismissalOut,
    ProductEventIn,
    ProductEventOut,
)

ROOT = Path(__file__).resolve().parents[1]


def examples():
    event = "synthetic-event"
    insight = "synthetic-insight"
    values = [
        ("hide_event", DismissalIn, {"event_id": event, "hidden": True}),
        ("restore_insight", DismissalIn, {"event_id": event, "insight_id": insight, "hidden": False}),
        ("hidden", DismissalOut, {"event_id": event, "version": "*", "hidden": True}),
        (
            "contact_request",
            DemoActionIn,
            {
                "event_id": event,
                "insight_id": insight,
                "action_type": "contact_manager",
                "idempotency_key": "synthetic-action-001",
            },
        ),
        (
            "recorded_demo",
            DemoActionOut,
            {
                "id": "synthetic-action",
                "company_id": "synthetic-company",
                "event_id": event,
                "insight_id": insight,
                "action_type": "contact_manager",
                "mode": "demo",
                "status": "recorded",
                "created_at": "2026-10-22T12:00:00Z",
            },
        ),
        (
            "impression",
            ProductEventIn,
            {"event_id": event, "insight_id": insight, "event_type": "impression"},
        ),
        (
            "duplicate_impression",
            ProductEventOut,
            {
                "id": "synthetic-product-event",
                "event_type": "impression",
                "recorded": False,
                "excluded_reason": None,
            },
        ),
    ]
    return [
        {"name": name, "schema": model.__name__, "data": model.model_validate(value).model_dump(mode="json")}
        for name, model, value in values
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "docs/contracts/interaction-examples.json"
    value = json.dumps(examples(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        assert path.read_text(encoding="utf-8") == value, "interaction examples drift"
    else:
        path.write_text(value, encoding="utf-8")


if __name__ == "__main__":
    main()

"""Generate A15 shared fixtures and JSON Schema from the backend contract."""

import argparse
import json
from copy import deepcopy
from pathlib import Path

from app.schemas import FeedSnapshotOut
from app.services.feed_ranking import RANKING_VERSION

ROOT = Path(__file__).resolve().parents[1]


def artifacts():
    contract = ROOT / "docs/contracts"
    fixture = next(
        value
        for value in json.loads((contract / "insight-v2-examples.json").read_text(encoding="utf-8"))
        if value["name"] == "long_lived_active_insight"
    )
    result = fixture["envelope"]["result"]
    versions = dict(
        profile="synthetic-v2",
        event="synthetic-event",
        focus="synthetic-focus",
        corpus="synthetic-corpus",
        prompt="synthetic-prompt",
        model="synthetic-model",
        semantics="synthetic-semantics",
        contract="impact-contract-2",
    )
    base = dict(
        schema_version="v2",
        snapshot_id="synthetic-snapshot",
        generation_status="queued",
        versions={"inputs": versions},
        stale=False,
        stale_reasons=[],
        ranking_version=RANKING_VERSION,
        ranking_as_of="2026-10-22T12:00:00Z",
        ready_at=None,
        job_id="synthetic-job",
        error=None,
        items=[],
        total=0,
        limit=20,
        offset=0,
        next_offset=None,
    )
    ready = deepcopy(base)
    ready.update(generation_status="ready", ready_at="2026-10-22T12:00:10Z", total=1)
    ready["items"] = [
        dict(
            event_id="synthetic-event",
            title="Учебное событие",
            summary=None,
            published_at="2026-01-01T12:00:00Z",
            rank_score=32,
            relevance_reasons=[dict(factor="impact", evidence_refs=result["evidence_refs"], contribution=20)],
            status="done",
            sources=[],
            generation_status="ready",
            insight_id="synthetic-insight",
            personalized_summary=result["personalized_summary"],
            **{
                key: result[key]
                for key in (
                    "mechanism",
                    "impact_reason",
                    "time_horizon",
                    "relevance_reason",
                    "valid_from",
                    "valid_until",
                    "review_after",
                    "unknowns",
                )
            },
            impact_level=result["impact_level"],
            relevance_status=result["relevance_status"],
            versions=versions,
            error=None,
        )
    ]
    deferred = deepcopy(ready)
    deferred.update(generation_status="deferred", error={"code": "budget_exhausted"})
    deferred["items"][0].update(
        generation_status="deferred",
        insight_id=None,
        personalized_summary=None,
        impact_level="undetermined",
        relevance_status="undetermined",
        error={"code": "budget_exhausted"},
        mechanism=[],
        impact_reason=None,
        time_horizon=None,
        relevance_reason=None,
        valid_from=None,
        valid_until=None,
        review_after=None,
        unknowns=[],
    )
    examples = [
        dict(
            name=name,
            schema="FeedSnapshotOut",
            data=FeedSnapshotOut.model_validate(value).model_dump(mode="json"),
        )
        for name, value in [("queued", base), ("ready", ready), ("deferred", deferred)]
    ]
    return {
        "feed-snapshot-v2.schema.json": FeedSnapshotOut.model_json_schema(),
        "feed-snapshot-v2-examples.json": examples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, value in artifacts().items():
        path = ROOT / "docs/contracts" / name
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if path.read_text(encoding="utf-8") != text:
                raise SystemExit(f"Outdated feed contract {name}")
        else:
            path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

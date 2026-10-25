"""Synthetic v2 producer for offline snapshot/access tests only."""

from uuid import uuid4

from tests.fake_ai import allowed
from tests.fake_ai import derive_user_focus as derive_user_focus


def build_insight(company_context, user_focus, event, tools):
    assert tools.get_company_context()["company_id"] == company_context["company_id"]
    publication = event["evidence"][0]
    feature = next(name for name, entry in company_context["features"].items() if entry.get("value"))
    company_ref = str(uuid4())
    refs = [publication["id"], company_ref]

    def statement(name, kind="hypothesis"):
        return dict(claim_id=name, text=f"Synthetic test {name}", evidence_refs=refs, statement_type=kind)

    return allowed(
        {
            "result": dict(
                schema_version="v2",
                facts=[statement("fact", "fact")],
                bank_view=None,
                ai_interpretation=[statement("interpretation")],
                risks=[],
                opportunities=[],
                actions=[],
                unknowns=["Synthetic bank evidence unavailable"],
                evidence_refs=refs,
                trace_id=str(uuid4()),
                personalized_summary=statement("summary"),
                mechanism=[statement("mechanism")],
                impact_level="medium",
                impact_reason=statement("impact"),
                time_horizon=dict(label="Synthetic long term", starts_on=None, ends_on=None),
                assumptions=[],
                relevance_status="active",
                valid_from="2020-01-01",
                valid_until=None,
                review_after=None,
                relevance_reason=statement("relevance"),
                bank_view_context=dict(status="missing", document_dates=[]),
                next_actions=[],
            ),
            "evidence": [
                publication,
                dict(
                    id=company_ref,
                    kind="company",
                    source_id=company_context["company_id"],
                    version=company_context["profile_version"],
                    locator={"feature_path": f"features.{feature}"},
                    excerpt="Synthetic fixture feature",
                ),
            ],
            "trace": {"mode": "synthetic-test"},
        }
    )

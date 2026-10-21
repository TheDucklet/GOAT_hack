"""Cross-field v2 checks reused by AI envelopes and the worker boundary."""

from datetime import date

from app.schemas import EvidenceOut, InsightResultV2


def validate_v2_provenance(result: InsightResultV2, evidence: list[EvidenceOut]) -> None:
    catalogue = {item.id: item for item in evidence}
    if len(catalogue) != len(evidence):
        raise ValueError("envelope evidence ids must be unique")
    if set(result.evidence_refs) != set(catalogue):
        raise ValueError("v2 envelope must contain exactly all referenced evidence")
    bank_dates = set()
    for claim in result.bank_view or []:
        for ref in claim.evidence_refs:
            item = catalogue[ref]
            if item.kind != "bank":
                raise ValueError("bank_view can only cite bank evidence")
            document_date = item.locator.get("document_date")
            if document_date is not None:
                if not isinstance(document_date, str):
                    raise ValueError("document_date must be an ISO date string")
                bank_dates.add(date.fromisoformat(document_date))
            elif result.bank_view_context.status != "undated":
                raise ValueError("dated bank_view requires document_date in each locator")
    if bank_dates != set(result.bank_view_context.document_dates):
        raise ValueError("bank_view dates must match the cited documents")

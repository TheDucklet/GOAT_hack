"""Shared cache namespace. Bump before changing output or input semantics."""

from app.data_semantics import DATA_SEMANTICS_VERSION
from app.notice_policy import POLICY_VERSION

INSIGHT_CONTRACT_VERSION = "impact-contract-2"
INSIGHT_SCHEMA_VERSION = "v1"  # F-14 switches the producer, not F-13's contract publication.


def contract_versions(semantics_version: str | None = None) -> dict[str, str]:
    return {
        "contract": INSIGHT_CONTRACT_VERSION,
        "schema": INSIGHT_SCHEMA_VERSION,
        "semantics": DATA_SEMANTICS_VERSION,
        "context_semantics": semantics_version or DATA_SEMANTICS_VERSION,
        "policy": POLICY_VERSION,
    }

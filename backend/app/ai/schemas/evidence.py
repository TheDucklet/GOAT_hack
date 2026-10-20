from typing import Literal

from pydantic import model_validator

from app.schemas import EvidenceOut, Schema

FEATURE_PATH_PREFIX = "features."


def locator_problem(kind: str, locator: dict) -> str | None:
    if kind == "news":
        url = locator.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return "news locator requires an absolute http(s) url"
    elif kind == "bank":
        page = locator.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            return "bank locator requires page >= 1"
    elif kind == "company":
        path = locator.get("feature_path")
        if (
            not isinstance(path, str)
            or not path.startswith(FEATURE_PATH_PREFIX)
            or path == FEATURE_PATH_PREFIX
        ):
            return "company locator requires feature_path of the form features.<COLUMN>"
    return None


class GroundedEvidence(EvidenceOut):
    @model_validator(mode="after")
    def locator_matches_kind(self):
        problem = locator_problem(self.kind, self.locator)
        if problem:
            raise ValueError(problem)
        if not self.excerpt.strip():
            raise ValueError("evidence excerpt must not be empty")
        if not self.source_id.strip() or not self.version.strip():
            raise ValueError("evidence requires source_id and version")
        return self


class EvidenceTarget(Schema):
    type: Literal["url", "pdf_page", "company_feature"]
    source_id: str
    href: str | None = None
    page: int | None = None
    feature_path: str | None = None


def evidence_target(evidence: EvidenceOut) -> EvidenceTarget:
    if evidence.kind == "news":
        return EvidenceTarget(type="url", source_id=evidence.source_id, href=evidence.locator["url"])
    if evidence.kind == "bank":
        return EvidenceTarget(type="pdf_page", source_id=evidence.source_id, page=evidence.locator["page"])
    return EvidenceTarget(
        type="company_feature", source_id=evidence.source_id, feature_path=evidence.locator["feature_path"]
    )

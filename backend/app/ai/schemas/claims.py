from pydantic import field_validator, model_validator

from app.schemas import Claim


class GroundedClaim(Claim):
    @field_validator("claim_id", "text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("claim_id and text must not be blank")
        return value

    @model_validator(mode="after")
    def has_unique_evidence(self):
        if not self.evidence_refs:
            raise ValueError(f"claim {self.claim_id} has no evidence_refs")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError(f"claim {self.claim_id} repeats an evidence ref")
        if any(not ref.strip() for ref in self.evidence_refs):
            raise ValueError(f"claim {self.claim_id} has a blank evidence ref")
        return self

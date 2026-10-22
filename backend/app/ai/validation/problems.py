from dataclasses import dataclass

SUPPORTED = "supported"
INSUFFICIENT = "insufficient"
CONTRADICTION = "contradiction"


@dataclass(frozen=True)
class Problem:
    code: str
    detail: str
    verdict: str = INSUFFICIENT

from typing import Annotated

from pydantic import BeforeValidator, Field

from app.ai.summarization.summarize import Lenient, StrList, to_dict_list


class RawStatement(Lenient):
    text: str = ""
    evidence_ids: StrList = Field(default_factory=list)


def to_statement(value):
    if isinstance(value, str):
        return {"text": value}
    return value if isinstance(value, dict) else None


def to_statements(value):
    if isinstance(value, dict):
        return [value]
    items = to_dict_list(value)
    return (
        items
        if items or not isinstance(value, list)
        else [{"text": item} for item in value if isinstance(item, str)]
    )


OptionalStatement = Annotated[RawStatement | None, BeforeValidator(to_statement)]
Statements = Annotated[list[RawStatement], BeforeValidator(to_statements)]


class RawHorizon(Lenient):
    kind: str = "unknown"
    label: str = ""
    starts_on: str | None = None
    ends_on: str | None = None


def to_horizon(value):
    return value if isinstance(value, dict) else {}


class RawImpact(Lenient):
    summary: OptionalStatement = None
    mechanism: Statements = Field(default_factory=list)
    impact_level: str = "undetermined"
    impact_reason: OptionalStatement = None
    horizon: Annotated[RawHorizon, BeforeValidator(to_horizon)] = Field(default_factory=RawHorizon)
    assumptions: Statements = Field(default_factory=list)
    relevance_reason: OptionalStatement = None
    unknowns: StrList = Field(default_factory=list)

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator


def to_str_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item is not None]


def to_dict_list(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


StrList = Annotated[list[str], BeforeValidator(to_str_list)]


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def drop_nulls(cls, data):
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data

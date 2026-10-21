import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_LIMITS_PATH = Path(__file__).with_name("limits.json")


class BudgetConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    daily_limit_rub: float = Field(default=500, gt=0)
    utc_offset_hours: int = 3
    day_starts_at_hour: int = Field(default=3, ge=0, le=23)
    chars_per_token: float = Field(default=2.0, gt=0)
    image_tokens: int = Field(default=4000, ge=0)

    @classmethod
    def load(cls, path: Path = DEFAULT_LIMITS_PATH) -> "BudgetConfig":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def day_of(self, moment: datetime) -> date:
        local = moment.astimezone(timezone(timedelta(hours=self.utc_offset_hours)))
        return (local - timedelta(hours=self.day_starts_at_hour)).date()

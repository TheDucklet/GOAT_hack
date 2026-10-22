import re
from datetime import date

CURRENT_DAYS = 120
HISTORICAL_DAYS = 365
YEAR = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")

STATUS_REASONS = {
    "current": "документ опубликован не раньше чем за 120 дней до даты события",
    "historical": "документ старше года",
    "undated": "дата документа неизвестна",
    "period_expired": "период, о котором говорит текст, закончился до даты события",
    "applicability_unknown": "документ старше 120 дней, а период применения в тексте не назван",
}


def latest_year(text: str) -> int | None:
    years = [int(item) for item in YEAR.findall(text)]
    return max(years) if years else None


def temporal_status(document_date: str | None, text: str, as_of: date) -> tuple[str, str]:
    if not document_date:
        return "undated", STATUS_REASONS["undated"]
    age = (as_of - date.fromisoformat(document_date)).days
    if age > HISTORICAL_DAYS:
        return "historical", STATUS_REASONS["historical"]
    if age <= CURRENT_DAYS:
        return "current", STATUS_REASONS["current"]
    year = latest_year(text)
    if year is None:
        return "applicability_unknown", STATUS_REASONS["applicability_unknown"]
    if year < as_of.year:
        return "period_expired", STATUS_REASONS["period_expired"]
    return "current", "текст относится к периоду, который включает дату события"

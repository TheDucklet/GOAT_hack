import re
from datetime import date

MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}
WORD_DATE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.IGNORECASE)
DOT_DATE = re.compile(r"\b(\d{1,2})\.(\d{2})\.(\d{4})\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def dates_in(text: str) -> set[date]:
    found = set()
    for day, month, year in WORD_DATE.findall(text):
        found.add(safe_date(int(year), MONTHS[month.lower()], int(day)))
    for day, month, year in DOT_DATE.findall(text):
        found.add(safe_date(int(year), int(month), int(day)))
    for year, month, day in ISO_DATE.findall(text):
        found.add(safe_date(int(year), int(month), int(day)))
    found.discard(None)
    return found


def parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def grounded_date(value: str | None, sources: str) -> date | None:
    parsed = parse_iso(value)
    if parsed is None or parsed not in dates_in(sources):
        return None
    return parsed

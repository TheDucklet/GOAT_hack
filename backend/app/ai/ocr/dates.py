import calendar
import re
from datetime import date

RU_MONTHS = {
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

RU_MONTHS_NOMINATIVE = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}

EN_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

RU_DATE = re.compile(r"(\d{1,2})\s+(" + "|".join(RU_MONTHS) + r")\s+(\d{4})", re.IGNORECASE)
NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
EN_DAY_FIRST = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b")
EN_MONTH_FIRST = re.compile(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b")

YEAR = re.compile(r"\b(20\d{2})\b")
DAY_MONTH = re.compile(r"(\d{1,2})\s+(" + "|".join(RU_MONTHS) + r")\b(?!\s+\d{4})", re.IGNORECASE)
MONTH_YEAR = re.compile(r"\b(" + "|".join(RU_MONTHS_NOMINATIVE) + r")\s+(\d{4})\b", re.IGNORECASE)

HEADER_SCAN_CHARS = 900
MIN_YEAR = 2000


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_dates(text: str) -> list[tuple[int, date]]:
    found: list[tuple[int, date]] = []
    for match in RU_DATE.finditer(text):
        parsed = _safe(int(match[3]), RU_MONTHS[match[2].lower()], int(match[1]))
        if parsed:
            found.append((match.start(), parsed))
    for match in NUMERIC_DATE.finditer(text):
        parsed = _safe(int(match[3]), int(match[2]), int(match[1]))
        if parsed:
            found.append((match.start(), parsed))
    for match in EN_DAY_FIRST.finditer(text):
        month = EN_MONTHS.get(match[2].lower())
        parsed = month and _safe(int(match[3]), month, int(match[1]))
        if parsed:
            found.append((match.start(), parsed))
    for match in EN_MONTH_FIRST.finditer(text):
        month = EN_MONTHS.get(match[1].lower())
        parsed = month and _safe(int(match[3]), month, int(match[2]))
        if parsed:
            found.append((match.start(), parsed))
    return sorted(found)


def parse_first_date(text: str) -> date | None:
    dates = parse_dates(text)
    return dates[0][1] if dates else None


def document_date(
    first_page_text: str, printed_date_text: str | None, today: date | None = None
) -> date | None:
    today = today or date.today()
    header = first_page_text[:HEADER_SCAN_CHARS]
    if printed_date_text:
        printed = parse_first_date(printed_date_text)
        if printed and printed <= today and _appears_in(printed, first_page_text):
            return printed
    in_header = [found for _, found in parse_dates(header) if found <= today]
    if in_header:
        return in_header[0]
    return _without_year(first_page_text, header, printed_date_text, today) or _month_only(header, today)


def _appears_in(candidate: date, text: str) -> bool:
    return any(found == candidate for _, found in parse_dates(text))


def _page_year(text: str, today: date) -> int | None:
    years = [int(year) for year in YEAR.findall(text) if MIN_YEAR <= int(year) <= today.year]
    if not years:
        return None
    return max(set(years), key=lambda year: (years.count(year), year))


def _without_year(
    first_page_text: str, header: str, printed_date_text: str | None, today: date
) -> date | None:
    year = _page_year(first_page_text + " " + (printed_date_text or ""), today)
    if year is None:
        return None
    for source in (printed_date_text or "", header):
        match = DAY_MONTH.search(source)
        if match:
            parsed = _safe(year, RU_MONTHS[match[2].lower()], int(match[1]))
            if parsed and parsed <= today:
                return parsed
    return None


def _month_only(header: str, today: date) -> date | None:
    match = MONTH_YEAR.search(header)
    if not match:
        return None
    year, month = int(match[2]), RU_MONTHS_NOMINATIVE[match[1].lower()]
    if not MIN_YEAR <= year <= today.year:
        return None
    return min(date(year, month, calendar.monthrange(year, month)[1]), today)

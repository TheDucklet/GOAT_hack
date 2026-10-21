import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.ai.ocr.dates import document_date
from app.ai.ocr.engine import PageResult, recognize_page
from app.ai.ocr.render import file_sha256, page_count
from app.ai.ocr.settings import OcrSettings, get_ocr_settings

MAX_TITLE_CHARS = 200
GENERIC_HEADERS = re.compile(
    r"центр\s+макроэкономическ|^рынок\s+облигаций$|^\d{1,2}\s+\w+\s+\d{4}", re.IGNORECASE
)


@dataclass(frozen=True)
class OcrDocument:
    path: Path
    sha256: str
    pages: list[PageResult]
    title: str | None
    document_date: date | None
    date_unknown: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "date_unknown", self.document_date is None)

    @property
    def failed_pages(self) -> list[PageResult]:
        return [page for page in self.pages if page.status != "ok"]

    @property
    def non_empty_pages(self) -> int:
        return sum(1 for page in self.pages if page.status == "ok" and page.text.strip())


def ocr_document(
    path: Path,
    settings: OcrSettings | None = None,
    pages: list[int] | None = None,
    use_cache: bool = True,
) -> OcrDocument:
    settings = settings or get_ocr_settings()
    sha256 = file_sha256(path)
    selected = pages or list(range(1, page_count(path) + 1))
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        results = list(
            pool.map(lambda number: recognize_page(path, sha256, number, settings, use_cache), selected)
        )
    first = next((page for page in results if page.page == 1), None)
    title = _title(first)
    published = document_date(first.text, first.date_text) if first and first.status == "ok" else None
    return OcrDocument(path, sha256, results, title, published)


def _is_generic(line: str) -> bool:
    return bool(GENERIC_HEADERS.search(line))


def _title(first: PageResult | None) -> str | None:
    if first is None or first.status != "ok":
        return None
    lines = [line.strip() for line in first.text.splitlines() if line.strip()]
    candidates = [first.title, *lines] if first.title else lines
    candidate = next((line for line in candidates if not _is_generic(line)), None)
    return candidate[:MAX_TITLE_CHARS] if candidate else None

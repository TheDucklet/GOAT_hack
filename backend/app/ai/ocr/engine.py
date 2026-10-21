import json
from dataclasses import dataclass
from pathlib import Path

from app.ai.ocr.render import png_data_url, render_page_png, render_page_tiles
from app.ai.ocr.settings import OCR_PROMPT_VERSION, OCR_TASK, OcrSettings
from app.ai.providers import LLMError, LLMInput, call_llm, get_llm_settings

SYSTEM_PROMPT = (
    "Ты распознаёшь текст страницы аналитического отчёта банка по изображению. "
    "Изображение может быть верхней или нижней частью страницы. "
    "Верни только JSON-объект с полями text, title, date_text. "
    "В поле text дословно перепиши весь видимый текст изображения в порядке чтения, "
    "колонки читай по очереди сверху вниз. "
    "Числа, знаки, единицы измерения, проценты и даты переписывай без изменений. "
    "Строки таблиц переноси отдельными строками, ячейки разделяй символом |. "
    "У графиков и диаграмм перепиши заголовок, легенду и подписи значений, которые видны на изображении, "
    "а у осей укажи название и крайние значения, не перечисляя все деления. "
    "Каждый фрагмент текста выводи один раз, повторы недопустимы. "
    "Ничего не добавляй, не пересчитывай и не поясняй. "
    "Если на изображении нет напечатанного текста, например фотография или иллюстрация, "
    "верни text равным пустой строке, ничего не придумывай и не описывай картинку. "
    "В поле title укажи название документа, если оно напечатано на изображении, иначе null. "
    "В поле date_text дословно укажи дату публикации документа, если она напечатана на изображении, иначе null."
)
FREQUENCY_PENALTY = None
RETRY_FREQUENCY_PENALTY = 0.2
RETRY_TEMPERATURE = 0.5
FIRST_ATTEMPT_TEMPERATURE = 0.0


@dataclass(frozen=True)
class PageResult:
    page: int
    status: str
    text: str
    title: str | None
    date_text: str | None
    failure: str | None
    engine: str
    input_tokens: int
    output_tokens: int
    cost_rub: float
    cached: bool


@dataclass
class Spent:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_rub: float = 0.0
    engine: str = ""


def _cache_file(cache_dir: Path, sha256: str, page: int) -> Path:
    return cache_dir / sha256 / f"{OCR_PROMPT_VERSION}-p{page:03d}.json"


def _load_cached(cache_dir: Path, sha256: str, page: int, model_id: str) -> PageResult | None:
    path = _cache_file(cache_dir, sha256, page)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("engine") != model_id:
        return None
    return PageResult(
        page,
        "ok",
        data["text"],
        data.get("title"),
        data.get("date_text"),
        None,
        data["engine"],
        data["input_tokens"],
        data["output_tokens"],
        data["cost_rub"],
        True,
    )


def _store(cache_dir: Path, sha256: str, result: PageResult) -> None:
    path = _cache_file(cache_dir, sha256, result.page)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "text": result.text,
        "title": result.title,
        "date_text": result.date_text,
        "engine": result.engine,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_rub": result.cost_rub,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text_field(data: dict, key: str) -> str | None:
    value = data.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _with_title_as_text(data: dict) -> dict:
    if _text_field(data, "text"):
        return data
    parts = [_text_field(data, "title"), _text_field(data, "date_text")]
    return {**data, "text": "\n".join(part for part in parts if part)}


def _recognize_tile(
    png: bytes, label: str, settings: OcrSettings, spent: Spent, attempts: int, max_tokens: int
) -> tuple[dict | None, str]:
    request = LLMInput(system=SYSTEM_PROMPT, user=f"Распознай {label}.", image_data_urls=(png_data_url(png),))
    failure = "unknown"
    for attempt in range(attempts):
        retry = attempt > 0
        try:
            result = call_llm(
                OCR_TASK,
                request,
                max_tokens,
                timeout_seconds=settings.request_timeout_seconds,
                temperature=RETRY_TEMPERATURE if retry else FIRST_ATTEMPT_TEMPERATURE,
                frequency_penalty=RETRY_FREQUENCY_PENALTY if retry else FREQUENCY_PENALTY,
            )
        except LLMError as error:
            if error.code in {"budget_exhausted", "model_not_allowed", "ai_unavailable"}:
                raise
            failure = error.code
            continue
        spent.engine = result.model_id
        spent.input_tokens += result.usage.input_tokens
        spent.output_tokens += result.usage.output_tokens
        spent.cost_rub += result.usage.cost_rub
        data = _with_title_as_text(result.data)
        if not _text_field(data, "text"):
            failure = "empty_text"
            continue
        return data, failure
    if failure == "empty_text":
        return {"text": ""}, failure
    return None, failure


def recognize_page(
    pdf_path: Path, sha256: str, page: int, settings: OcrSettings, use_cache: bool = True
) -> PageResult:
    if use_cache:
        cached = _load_cached(
            settings.cache_dir, sha256, page, get_llm_settings().llm_task_models.get(OCR_TASK, "")
        )
        if cached:
            return cached
    spent = Spent()
    whole = _recognize_whole_page(pdf_path, page, settings, spent)
    if whole is not None:
        result = _result(page, "ok", whole["text"], whole["title"], whole["date_text"], None, spent)
        _store(settings.cache_dir, sha256, result)
        return result
    return _recognize_by_tiles(pdf_path, sha256, page, settings, spent)


def _recognize_whole_page(pdf_path: Path, page: int, settings: OcrSettings, spent: Spent) -> dict | None:
    png = render_page_png(pdf_path, page, settings.dpi, settings.max_side_pixels)
    data, _ = _recognize_tile(png, "страницу целиком", settings, spent, 1, settings.page_max_tokens)
    text = _text_field(data or {}, "text")
    if text is None:
        return None
    return {"text": text, "title": _text_field(data, "title"), "date_text": _text_field(data, "date_text")}


def _recognize_by_tiles(
    pdf_path: Path, sha256: str, page: int, settings: OcrSettings, spent: Spent
) -> PageResult:
    tiles = render_page_tiles(
        pdf_path, page, settings.dpi, settings.max_side_pixels, settings.tile_height_pixels
    )
    texts: list[str] = []
    title = date_text = None
    for index, png in enumerate(tiles, start=1):
        label = f"фрагмент {index} из {len(tiles)}"
        data, failure = _recognize_tile(
            png, label, settings, spent, settings.page_attempts, settings.max_tokens
        )
        if data is None:
            return _result(page, "failed", "", None, None, failure, spent)
        texts.append(_text_field(data, "text") or "")
        if index == 1:
            title, date_text = _text_field(data, "title"), _text_field(data, "date_text")
        elif date_text is None:
            date_text = _text_field(data, "date_text")
    text = "\n".join(part for part in texts if part)
    if len(text) < settings.min_page_chars:
        return _result(page, "failed", "", None, None, "empty_text", spent)
    result = _result(page, "ok", text, title, date_text, None, spent)
    _store(settings.cache_dir, sha256, result)
    return result


def _result(
    page: int,
    status: str,
    text: str,
    title: str | None,
    date_text: str | None,
    failure: str | None,
    spent: Spent,
) -> PageResult:
    return PageResult(
        page,
        status,
        text,
        title,
        date_text,
        failure,
        spent.engine,
        spent.input_tokens,
        spent.output_tokens,
        round(spent.cost_rub, 6),
        False,
    )

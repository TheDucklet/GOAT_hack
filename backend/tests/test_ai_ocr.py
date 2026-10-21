import json
from datetime import date
from pathlib import Path

import pypdfium2
import pytest

from app.ai.ocr import build_ingest_result, ingest_bank_document
from app.ai.ocr.dates import document_date, parse_dates
from app.ai.ocr.engine import PageResult, recognize_page
from app.ai.ocr.pipeline import OcrDocument
from app.ai.ocr.render import file_sha256, page_count, render_page_png
from app.ai.ocr.settings import OcrSettings
from app.ai.providers import LLMSettings, MemoryUsageSink
from app.ai.providers import gateway as gateway_module
from app.ai.providers.testing import ScriptedTransport, json_completion
from app.ai.rag.chunking import ChunkSettings, split_text
from app.integrations.ai import AIError


def make_pdf(path: Path, pages: int) -> Path:
    document = pypdfium2.PdfDocument.new()
    for _ in range(pages):
        document.new_page(595, 842)
    document.save(str(path))
    document.close()
    return path


def page(number, text="Ключевая ставка 14,0% годовых", status="ok", title=None, date_text=None):
    return PageResult(
        number,
        status,
        text if status == "ok" else "",
        title,
        date_text,
        None if status == "ok" else "empty_text",
        "qwen/qwen3-vl-30b-a3b-instruct",
        100,
        50,
        0.01,
        False,
    )


def recognized(pages, published=None):
    return OcrDocument(Path("doc.pdf"), "0" * 64, pages, "Название", published)


def test_russian_long_date_is_parsed():
    assert document_date("Решение от 11 сентября 2026 года", None) == date(2026, 9, 11)


def test_numeric_and_english_dates_are_parsed():
    found = [item[1] for item in parse_dates("14.09.2026 и 15 Apr 2021 и Sep 11, 2026")]
    assert date(2026, 9, 14) in found and date(2021, 4, 15) in found and date(2026, 9, 11) in found


def test_invalid_calendar_date_is_ignored():
    assert parse_dates("31.02.2026") == []


def test_printed_date_must_appear_in_page_text():
    assert document_date("Без даты в тексте", "5 мая 2026") is None


def test_date_is_taken_from_header_only():
    far = "слово " * 400 + "1 января 2030 года"
    assert document_date(far, None) is None


def test_missing_date_gives_unknown_flag():
    doc = recognized([page(1)], published=None)
    assert doc.date_unknown is True
    assert recognized([page(1)], date(2026, 9, 11)).date_unknown is False


def test_chunks_respect_size_and_overlap():
    text = ("Слово " * 700).strip()
    chunks = split_text(text, 1200, 200)
    assert all(len(chunk.text) <= 1200 for chunk in chunks)
    assert len(chunks) >= 4
    assert chunks[1].start < chunks[0].end


def test_short_text_gives_single_chunk():
    chunks = split_text("Короткий текст страницы", 1200, 200)
    assert [chunk.text for chunk in chunks] == ["Короткий текст страницы"]


def test_overlap_not_smaller_than_chunk_is_rejected():
    with pytest.raises(ValueError):
        split_text("текст", 300, 300)


def test_chunk_settings_defaults_match_task():
    settings = ChunkSettings(_env_file=None)
    assert (settings.chunk_chars, settings.overlap_chars) == (1200, 200)


def test_ingest_result_keeps_pdf_page_numbers_not_chunk_order():
    pages = [page(1, "а " * 900), page(2, "Вторая страница"), page(3, "Третья страница")]
    result = build_ingest_result(recognized(pages))
    numbers = [chunk["page"] for chunk in result["chunks"]]
    assert numbers == sorted(numbers)
    assert set(numbers) == {1, 2, 3}
    assert numbers.count(1) > 1
    assert [chunk["quality"]["chunk_index"] for chunk in result["chunks"] if chunk["page"] == 1][:2] == [0, 1]


def test_failed_page_makes_ingest_fail_instead_of_indexing():
    with pytest.raises(AIError) as raised:
        build_ingest_result(recognized([page(1), page(2, status="failed")]))
    assert raised.value.code == "invalid_ocr"
    assert "2" in raised.value.message


def test_ingest_result_contains_iso_date_or_null():
    assert build_ingest_result(recognized([page(1)], date(2026, 9, 11)))["document_date"] == "2026-09-11"
    assert build_ingest_result(recognized([page(1)]))["document_date"] is None


def test_pdf_helpers_report_pages_hash_and_png(tmp_path):
    pdf = make_pdf(tmp_path / "doc.pdf", 3)
    assert page_count(pdf) == 3
    assert len(file_sha256(pdf)) == 64
    png = render_page_png(pdf, 2, 150, 2000)
    assert png.startswith(b"\x89PNG")


def test_rendered_page_respects_maximum_side(tmp_path):
    import io

    from PIL import Image

    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    image = Image.open(io.BytesIO(render_page_png(pdf, 1, 300, 900)))
    assert max(image.size) <= 901


def llm_settings(**overrides):
    return LLMSettings(_env_file=None, llm_api_key="sk-test", llm_retry_backoff_seconds=0, **overrides)


def use_transport(monkeypatch, transport):
    original = gateway_module.call_llm

    def patched(task, input, max_tokens, **kwargs):
        return original(
            task,
            input,
            max_tokens,
            settings=llm_settings(),
            transport=transport,
            usage_sink=MemoryUsageSink(),
            sleep=lambda seconds: None,
            **kwargs,
        )

    monkeypatch.setattr("app.ai.ocr.engine.call_llm", patched)


def test_recognized_page_is_cached_and_not_requested_twice(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(_env_file=None, tile_height_pixels=5000, cache_dir=tmp_path / "cache")
    transport = ScriptedTransport(
        json_completion(
            {"text": "Ключевая ставка сохранена на уровне 14,0%", "title": "Ставка", "date_text": None}
        )
    )
    use_transport(monkeypatch, transport)
    sha = file_sha256(pdf)
    first = recognize_page(pdf, sha, 1, settings)
    second = recognize_page(pdf, sha, 1, settings)
    assert first.status == second.status == "ok"
    assert second.cached and transport.calls == 1
    assert second.text == first.text


def test_empty_recognition_is_marked_failed_and_not_cached(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=5000, cache_dir=tmp_path / "cache", page_attempts=2
    )
    empty = {"text": "", "title": None, "date_text": None}
    transport = ScriptedTransport(json_completion(empty), json_completion(empty), json_completion(empty))
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "failed" and result.failure == "empty_text"
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_page_is_retried_after_invalid_json(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=5000, cache_dir=tmp_path / "cache", page_attempts=2
    )
    from app.ai.providers.testing import completion

    transport = ScriptedTransport(
        completion("не JSON"),
        json_completion({"text": "Инфляция замедлилась до 6,1% г/г", "title": None, "date_text": None}),
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "ok" and transport.calls == 2


def test_ingest_rejects_missing_file_and_page_mismatch(tmp_path):
    with pytest.raises(AIError) as raised:
        ingest_bank_document(
            {"id": "d", "version": "v", "page_count": 1, "filename": "a.pdf"}, str(tmp_path / "none.pdf")
        )
    assert raised.value.code == "not_found"
    pdf = make_pdf(tmp_path / "doc.pdf", 2)
    with pytest.raises(AIError) as raised:
        ingest_bank_document({"id": "d", "version": "v", "page_count": 5, "filename": "a.pdf"}, str(pdf))
    assert raised.value.code == "invalid_ocr"


def test_cache_file_stores_usage_for_reports(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(_env_file=None, tile_height_pixels=5000, cache_dir=tmp_path / "cache")
    transport = ScriptedTransport(
        json_completion({"text": "Золото подорожало на 3,2%", "title": None, "date_text": None}, 900, 120)
    )
    use_transport(monkeypatch, transport)
    recognize_page(pdf, file_sha256(pdf), 1, settings)
    stored = json.loads(next((tmp_path / "cache").rglob("*.json")).read_text(encoding="utf-8"))
    assert stored["input_tokens"] == 900 and stored["output_tokens"] == 120


def test_page_is_cut_at_the_emptiest_row_between_text_blocks():
    from PIL import Image, ImageDraw

    from app.ai.ocr.render import cut_positions, row_ink, split_into_tiles

    image = Image.new("RGB", (400, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 100, 380, 460), fill="black")
    draw.rectangle((20, 540, 380, 900), fill="black")
    cut = cut_positions(row_ink(image), 2)[0]
    assert 460 <= cut <= 540
    tiles = split_into_tiles(image, 600)
    assert [tile.height for tile in tiles] == [cut, 1000 - cut]


def test_short_page_is_not_split():
    from PIL import Image

    from app.ai.ocr.render import split_into_tiles

    assert len(split_into_tiles(Image.new("RGB", (300, 500), "white"), 1000)) == 1


def test_tiles_of_one_page_are_recognized_separately_and_joined(tmp_path, monkeypatch):
    from app.ai.providers.testing import completion

    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=1000, dpi=150, cache_dir=tmp_path / "cache", page_attempts=1
    )
    transport = ScriptedTransport(
        completion("не JSON"),
        json_completion(
            {"text": "Верхняя часть: ставка 14,0%", "title": "Заголовок", "date_text": "11 сентября 2026"}
        ),
        json_completion({"text": "Нижняя часть: инфляция 6,1%", "title": None, "date_text": None}),
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert transport.calls == 3
    assert result.text == "Верхняя часть: ставка 14,0%" + chr(10) + "Нижняя часть: инфляция 6,1%"
    assert result.title == "Заголовок" and result.date_text == "11 сентября 2026"


def test_one_failed_tile_fails_the_whole_page_without_caching(tmp_path, monkeypatch):
    from app.ai.providers.testing import completion

    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=1000, dpi=150, cache_dir=tmp_path / "cache", page_attempts=1
    )
    transport = ScriptedTransport(
        completion("не JSON"),
        json_completion({"text": "Верхняя часть: ставка 14,0%", "title": None, "date_text": None}),
        completion("не JSON"),
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "failed" and result.failure == "invalid_json"
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_future_dates_such_as_bond_maturity_are_not_taken_as_publication_date():
    text = "Рынок облигаций\nБонд Бриф\nВ пятницу 11 сентября ЦБ сохранил ставку. ОФЗ (погашение 13.10.2040 г.)\nОбзор за 2026 год"
    assert document_date(text, "11 сентября", today=date(2026, 10, 21)) == date(2026, 9, 11)


def test_day_and_month_without_year_take_the_year_from_the_page():
    assert document_date("Вышло 7 мая. Прогноз на 2025 и 2025 годы", None, today=date(2026, 10, 21)) == date(
        2025, 5, 7
    )


def test_day_and_month_without_any_year_stay_unknown():
    assert document_date("Вышло 7 мая", None, today=date(2026, 10, 21)) is None


def test_month_and_year_title_gives_last_day_of_month():
    text = "ОБЗОР РЫНКА ЗОЛОТА\nАВГУСТ 2026"
    assert document_date(text, None, today=date(2026, 10, 21)) == date(2026, 8, 31)


def test_month_and_year_in_the_future_is_ignored():
    assert document_date("АВГУСТ 2030", None, today=date(2026, 10, 21)) is None


def test_page_with_only_title_keeps_the_title_as_text(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(_env_file=None, tile_height_pixels=5000, cache_dir=tmp_path / "cache")
    transport = ScriptedTransport(
        json_completion({"text": "", "title": "ОБЗОР РЫНКА ЗОЛОТА", "date_text": "АВГУСТ 2026"})
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "ok"
    assert "ОБЗОР РЫНКА ЗОЛОТА" in result.text and "АВГУСТ 2026" in result.text


def test_generic_center_header_is_not_used_as_title():
    from app.ai.ocr.pipeline import _title

    first = page(
        1,
        "ЦЕНТР МАКРОЭКОНОМИЧЕСКОГО АНАЛИЗА\n5 августа 2026 г.\nПотребление на пике\nТекст",
        title="Центр макроэкономического анализа",
    )
    assert _title(first) == "Потребление на пике"


def test_year_for_a_date_without_year_may_appear_anywhere_on_the_first_page():
    text = "Бонд Бриф\n11 сентября ЦБ сохранил ставку. " + "слово " * 200 + "Обзор 2026 года, погашение 2040"
    assert document_date(text, "11 сентября", today=date(2026, 10, 21)) == date(2026, 9, 11)


def test_picture_tile_without_text_does_not_fail_a_page_with_a_title(tmp_path, monkeypatch):
    from app.ai.providers.testing import completion

    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=1000, dpi=150, cache_dir=tmp_path / "cache", page_attempts=1
    )
    transport = ScriptedTransport(
        completion("не JSON"),
        json_completion(
            {"text": "ОБЗОР РЫНКА ЗОЛОТА" + chr(10) + "АВГУСТ 2026", "title": None, "date_text": None}
        ),
        json_completion({"text": "", "title": None, "date_text": None}),
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "ok" and result.text == "ОБЗОР РЫНКА ЗОЛОТА" + chr(10) + "АВГУСТ 2026"


def test_cut_avoids_text_on_a_dark_background():
    from PIL import Image, ImageDraw

    from app.ai.ocr.render import cut_positions, row_ink

    image = Image.new("RGB", (600, 1000), (15, 15, 25))
    draw = ImageDraw.Draw(image)
    for top in (430, 480, 560):
        for left in range(40, 560, 24):
            draw.rectangle((left, top, left + 12, top + 28), fill="white")
    cut = cut_positions(row_ink(image), 2)[0]
    assert not any(top - 2 <= cut <= top + 30 for top in (430, 480, 560))


def test_short_but_real_text_such_as_a_date_line_is_kept(tmp_path, monkeypatch):
    from app.ai.providers.testing import completion

    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(
        _env_file=None, tile_height_pixels=1000, dpi=150, cache_dir=tmp_path / "cache", page_attempts=1
    )
    transport = ScriptedTransport(
        completion("не JSON"),
        json_completion(
            {
                "text": "Долговой рынок" + chr(10) + "Тактический взгляд на 3-й квартал 2026г",
                "title": None,
                "date_text": None,
            }
        ),
        json_completion({"text": "22 июля 2026 г.", "title": None, "date_text": "22 июля 2026 г."}),
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert result.status == "ok" and result.text.endswith("22 июля 2026 г.")
    assert result.date_text == "22 июля 2026 г."


def test_whole_page_is_tried_first_and_tiles_are_not_requested_when_it_succeeds(tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "doc.pdf", 1)
    settings = OcrSettings(_env_file=None, tile_height_pixels=1000, dpi=150, cache_dir=tmp_path / "cache")
    transport = ScriptedTransport(
        json_completion({"text": "Страница целиком: ставка 14,0%", "title": "Ставка", "date_text": None})
    )
    use_transport(monkeypatch, transport)
    result = recognize_page(pdf, file_sha256(pdf), 1, settings)
    assert transport.calls == 1 and result.text == "Страница целиком: ставка 14,0%"
    assert transport.requests[0].max_tokens == settings.page_max_tokens

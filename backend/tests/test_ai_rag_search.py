import json
from datetime import date

import pytest

from app.ai.rag.search import (
    excerpt_for,
    is_historical,
    query_terms,
    required_terms,
    search_bank_analytics,
    search_variants,
    stem,
)


def chunk(chunk_id, text, page=1, document_date="2026-09-11", document_id="doc-1"):
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "version": "v1",
        "index_version": "i1",
        "page": page,
        "document_date": document_date,
        "date_unknown": document_date is None,
        "text": text,
    }


class FakeRepository:
    def __init__(self, chunks):
        self.chunks = chunks
        self.queries = []

    def search_chunks(self, query, as_of, limit=5):
        self.queries.append(query)
        words = [stem(word) for word in query.lower().split()]
        found = [
            item
            for item in self.chunks
            if all(word in item["text"].lower() for word in words)
            and (item["document_date"] is None or item["document_date"] <= as_of)
        ]
        return found[: max(1, min(limit, 20))]


RATE = chunk("c1", "Совет директоров сохранил ключевую ставку на уровне 14,0% годовых", page=1)
RATE_WEAK = chunk("c2", "Динамика кредитования зависит от ставки по кредитам", page=4, document_id="doc-2")
GOLD = chunk("c3", "Цена золота выросла за август на фоне слабого доллара", page=2, document_id="doc-3")
OLD = chunk(
    "c4", "Ключевая ставка была повышена до 17%", page=1, document_date="2021-04-15", document_id="doc-4"
)
UNDATED = chunk(
    "c5", "Ключевая ставка остаётся главным инструментом", page=3, document_date=None, document_id="doc-5"
)
LATER = chunk(
    "c6", "Ключевая ставка снижена в октябре", page=1, document_date="2026-10-23", document_id="doc-6"
)


def search(query, chunks, as_of="2026-09-30", limit=5):
    return search_bank_analytics(query, as_of, limit, FakeRepository(chunks))


def test_query_terms_drop_stop_words_and_keep_abbreviations_and_numbers():
    assert query_terms("Какое решение принял ЦБ по ставке 14,0") == [
        "решение",
        "принял",
        "цб",
        "ставке",
        "14,0",
    ]


def test_variants_start_with_the_full_query_and_end_with_single_terms():
    terms = ["ставка", "инфляция", "золото"]
    variants = search_variants("q", terms)
    assert variants[0] == "ставка инфляция золото"
    assert variants[-3:] == terms
    assert len(variants) == len(set(variants))


def test_required_coverage_grows_with_query_length():
    assert [required_terms(["a"] * n) for n in (1, 2, 3, 4, 6)] == [1, 2, 2, 3, 4]


def test_relevant_chunk_is_returned_with_page_excerpt_and_locator():
    result = search("ключевая ставка", [RATE, GOLD])
    top = result["items"][0]
    assert (top["page"], top["locator"]) == (1, {"page": 1})
    assert "ставку" in top["excerpt"]
    assert top["document_id"] == "doc-1" and top["version"] == "v1"


def test_chunk_matching_more_terms_ranks_first():
    result = search("ключевая ставка уровне", [RATE_WEAK, RATE])
    assert [item["chunk_id"] for item in result["items"]][0] == "c1"


def test_topic_without_evidence_gives_empty_list_and_reason_not_invented_fragment():
    result = search("прогноз цен на литий и кобальт", [RATE, GOLD, RATE_WEAK])
    assert result["items"] == []
    assert result["empty_reason"]


def test_document_later_than_as_of_is_excluded():
    ids = [item["chunk_id"] for item in search("ключевая ставка", [RATE, LATER], as_of="2026-09-30")["items"]]
    assert "c6" not in ids and "c1" in ids


def test_unknown_document_date_is_marked_explicitly():
    item = next(i for i in search("ключевая ставка", [UNDATED])["items"] if i["chunk_id"] == "c5")
    assert item["date_unknown"] is True and item["document_date"] is None


def test_historical_document_is_marked():
    item = search("ключевая ставка", [OLD])["items"][0]
    assert item["historical"] is True and item["date_unknown"] is False


def test_recent_document_is_not_marked_historical():
    assert search("ключевая ставка", [RATE])["items"][0]["historical"] is False


def test_limit_is_respected_and_capped_at_five():
    chunks = [chunk(f"c{i}", "Ключевая ставка сохранена", page=i + 1) for i in range(9)]
    assert len(search("ключевая ставка", chunks, limit=3)["items"]) == 3
    assert len(search("ключевая ставка", chunks, limit=5)["items"]) == 5
    with pytest.raises(ValueError):
        search("ключевая ставка", chunks, limit=6)


def test_duplicate_chunks_from_several_variants_are_returned_once():
    ids = [item["chunk_id"] for item in search("ключевая ставка уровне годовых", [RATE])["items"]]
    assert ids == ["c1"]


def test_invalid_as_of_is_rejected():
    with pytest.raises(ValueError):
        search("ставка", [RATE], as_of="30.09.2026")


def test_empty_query_is_rejected():
    with pytest.raises(ValueError):
        search("", [RATE])


def test_excerpt_is_a_window_around_the_matched_term_for_long_text():
    text = "вступление " * 80 + "ключевая ставка сохранена на уровне 14,0% " + "заключение " * 80
    excerpt = excerpt_for(text, ["ставка"])
    assert "ключевая ставка" in excerpt and len(excerpt) <= 330


def test_short_text_is_returned_as_is():
    assert excerpt_for("Короткий текст про ставку", ["ставка"]) == "Короткий текст про ставку"


def test_is_historical_uses_one_year_threshold():
    assert is_historical("2025-09-29", date(2026, 9, 30)) is True
    assert is_historical("2025-10-01", date(2026, 9, 30)) is False
    assert is_historical(None, date(2026, 9, 30)) is False


def test_result_is_valid_for_the_backend_tool_contract():
    from app.ai.schemas import BankSearchResult

    BankSearchResult.model_validate(search("ключевая ставка", [RATE]))


def test_file_repository_finds_chunks_by_all_words_and_filters_by_date(tmp_path):
    from app.ai.rag.file_repository import FileRepository

    chunks = [
        {**chunk("c1", "Ключевая ставка сохранена на уровне 14,0%"), "filename": "a.pdf"},
        {**chunk("c2", "Ключевая ставка будет снижена", document_date="2026-10-23"), "filename": "b.pdf"},
        {**chunk("c3", "Цена золота выросла"), "filename": "c.pdf"},
    ]
    path = tmp_path / "chunks.json"
    path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    repository = FileRepository(path)
    assert [item["chunk_id"] for item in repository.search_chunks("ключевая ставка", "2026-09-30")] == ["c1"]
    assert [item["chunk_id"] for item in repository.search_chunks("ключевая ставка", "2026-11-01")] == [
        "c1",
        "c2",
    ]
    assert repository.search_chunks("ключевая золота", "2026-09-30") == []
    assert repository.search_chunks("", "2026-09-30") == []


def test_search_works_on_top_of_the_file_repository(tmp_path):
    from app.ai.rag.file_repository import FileRepository

    path = tmp_path / "chunks.json"
    path.write_text(
        json.dumps([chunk("c1", "Ключевая ставка сохранена на уровне 14,0%")], ensure_ascii=False),
        encoding="utf-8",
    )
    result = search_bank_analytics("Какое решение по ключевой ставке", "2026-09-30", 5, FileRepository(path))
    assert [item["chunk_id"] for item in result["items"]] == ["c1"]

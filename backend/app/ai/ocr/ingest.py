from pathlib import Path

from app.ai.ocr.pipeline import OcrDocument, ocr_document
from app.ai.ocr.render import page_count
from app.ai.providers import LLMError
from app.ai.rag.chunking import ChunkSettings, split_text
from app.ai.schemas import GroundedIngestResult, IngestBankDocumentInput
from app.integrations.ai import AIError


def ingest_bank_document(document: dict, path: str) -> dict:
    request = IngestBankDocumentInput.model_validate({"document": document, "path": path})
    pdf_path = Path(request.path)
    if not pdf_path.is_file():
        raise AIError("not_found", "Файл документа не найден в хранилище")
    if page_count(pdf_path) != request.document.page_count:
        raise AIError("invalid_ocr", "Число страниц в PDF не совпадает с данными документа")
    try:
        recognized = ocr_document(pdf_path)
    except LLMError as error:
        raise AIError(error.code, error.message) from None
    return build_ingest_result(recognized)


def build_ingest_result(recognized: OcrDocument, chunk_settings: ChunkSettings | None = None) -> dict:
    failed = recognized.failed_pages
    if failed:
        numbers = ", ".join(str(page.page) for page in failed)
        raise AIError("invalid_ocr", f"Не удалось распознать страницы {numbers}, повторите загрузку позже")
    chunk_settings = chunk_settings or ChunkSettings()
    chunks = []
    for page in recognized.pages:
        for piece in split_text(page.text, chunk_settings.chunk_chars, chunk_settings.overlap_chars):
            chunks.append(
                {
                    "page": page.page,
                    "text": piece.text,
                    "quality": {
                        "engine": page.engine or "unknown",
                        "chunk_index": piece.index,
                        "char_start": piece.start,
                        "char_end": piece.end,
                        "confidence": None,
                    },
                }
            )
    result = GroundedIngestResult.model_validate(
        {
            "document_date": recognized.document_date.isoformat() if recognized.document_date else None,
            "chunks": chunks,
        }
    )
    return result.model_dump(mode="json")

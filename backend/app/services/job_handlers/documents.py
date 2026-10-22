"""OCR ingestion handler; page/version validation precedes persistence."""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from app.config import get_settings
from app.integrations.ai import AIError, call_ai
from app.models import BankDocument, Chunk
from app.schemas import AIEnvelope, EvidenceOut, IngestResult
from app.services.evidence import store_evidence


def ingest_document_job(db, job):
    doc = db.get(BankDocument, job.payload["document_id"])
    if not doc:
        raise AIError("not_found", "Документ не найден")
    from pathlib import Path

    result = IngestResult.model_validate(
        call_ai(
            "ingest_bank_document",
            document={
                "id": doc.id,
                "version": doc.version,
                "page_count": doc.page_count,
                "filename": doc.filename,
            },
            path=str(Path(get_settings().storage_dir).resolve() / doc.storage_key),
        )
    )
    checked = []
    for chunk in result.chunks:
        page = chunk.get("page")
        if (
            not isinstance(page, int)
            or not 1 <= page <= doc.page_count
            or (not chunk.get("text", "").strip())
        ):
            raise AIError("invalid_ocr", "OCR вернул некорректную страницу")
        checked.append(
            Chunk(
                document_id=doc.id,
                version=doc.version,
                page=page,
                text=chunk["text"],
                quality=chunk.get("quality", {}),
            )
        )
    if {c.page for c in checked} != set(range(1, doc.page_count + 1)):
        raise AIError("invalid_ocr", "OCR не содержит текст всех страниц")
    from sqlalchemy import delete

    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.add_all(checked)
    doc.index_version = hashlib.sha256(json.dumps(result.model_dump(), sort_keys=True).encode()).hexdigest()
    doc.document_date, doc.status, doc.error = (result.document_date, "done", None)
    first = next(chunk for chunk in checked if chunk.page == 1)
    source_id = str(uuid5(NAMESPACE_URL, f"bank:{doc.id}:{doc.version}:{doc.index_version}:1"))
    store_evidence(
        db,
        AIEnvelope(
            result={},
            evidence=[
                EvidenceOut(
                    id=source_id,
                    kind="bank",
                    source_id=doc.id,
                    version=doc.version,
                    locator={"page": 1, "document_date": doc.document_date},
                    excerpt=first.text[:2000],
                )
            ],
        ),
        None,
    )
    return {"document_id": doc.id, "chunks": len(checked), "source_id": source_id}

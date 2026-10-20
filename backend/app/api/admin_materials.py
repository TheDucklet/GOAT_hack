import hashlib
from io import BytesIO
from pathlib import PurePosixPath

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.errors import AppError
from app.models import (
    AuditLog,
    BankDocument,
    Event,
    Evidence,
    Job,
    News,
    Source,
    User,
)
from app.schemas import (
    AdminEventOut,
    DocumentOut,
    JobOut,
    UploadOut,
    VisibilityIn,
    VisibilityOut,
)
from app.security import admin_user
from app.services.jobs import enqueue

router = APIRouter(prefix="/admin", tags=["admin"])


def audit(db, admin, action, object_id, details=None):
    db.add(AuditLog(admin_id=admin.id, action=action, object_id=object_id, details=details or {}))


@router.get("/documents", response_model=list[DocumentOut])
def documents(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db, scope="function"),
):
    return list(db.scalars(select(BankDocument).order_by(BankDocument.id).offset(offset).limit(limit)))


@router.post("/documents", response_model=UploadOut, status_code=202)
def upload_document(
    file: UploadFile = File(...),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db, scope="function"),
):
    settings = get_settings()
    data = file.file.read(settings.max_pdf_bytes + 1)
    if len(data) > settings.max_pdf_bytes:
        raise AppError(413, "file_too_large", "Максимальный размер PDF — 50 МБ")
    if not data.startswith(b"%PDF-"):
        raise AppError(422, "invalid_pdf", "Требуется PDF-файл")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("encrypted")
        page_count = len(reader.pages)
        if not 1 <= page_count <= 1000:
            raise ValueError("page_count")
    except Exception as exc:
        raise AppError(
            422, "invalid_pdf", "PDF поврежден, зашифрован или содержит недопустимое число страниц"
        ) from exc
    sha = hashlib.sha256(data).hexdigest()
    previous = db.scalar(select(BankDocument).where(BankDocument.sha256 == sha))
    if previous:
        pending = db.scalar(select(Job).where(Job.dedup_key == f"document:{previous.id}"))
        source_id = db.scalar(
            select(Evidence.id).where(Evidence.kind == "bank", Evidence.source_id == previous.id)
        )
        return {"document": previous, "job": pending, "source_id": source_id}
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    key = f"{sha}.pdf"
    path = settings.storage_dir / key
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(data)
    filename = PurePosixPath((file.filename or "document.pdf").replace("\\", "/")).name[:255]
    doc = BankDocument(filename=filename, sha256=sha, version=sha, storage_key=key, page_count=page_count)
    db.add(doc)
    db.flush()
    evidence = Evidence(kind="bank", source_id=doc.id, version=doc.version, locator={"page": 1}, excerpt="")
    db.add(evidence)
    job = enqueue(db, "ingest_document", {"document_id": doc.id}, admin.id, dedup_key=f"document:{doc.id}")
    audit(db, admin, "upload_document", doc.id)
    return {"document": doc, "job": job, "source_id": evidence.id}


@router.post("/documents/{document_id}/reindex", response_model=JobOut, status_code=202)
def reindex(
    document_id: str, admin: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")
):
    doc = db.get(BankDocument, document_id)
    if not doc:
        raise AppError(404, "not_found", "Документ не найден")
    job = enqueue(db, "ingest_document", {"document_id": doc.id}, admin.id, dedup_key=f"document:{doc.id}")
    doc.status, doc.error = (job.status, None)
    audit(db, admin, "reindex_document", doc.id)
    return job


@router.get("/news", response_model=list[AdminEventOut])
def news(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db, scope="function"),
):
    events = list(
        db.scalars(
            select(Event)
            .order_by(Event.published_at.desc().nullslast(), Event.id)
            .offset(offset)
            .limit(limit)
        )
    )
    sources = {}
    for publication, name in db.execute(
        select(News, Source.name).join(Source).where(News.event_id.in_([e.id for e in events]))
    ):
        sources.setdefault(publication.event_id, []).append(
            {"id": publication.source_id, "name": name, "url": publication.url}
        )
    return [
        {
            "id": e.id,
            "title": e.title,
            "published_at": e.published_at,
            "visible": e.visible,
            "processing_status": e.processing_status,
            "sources": sources.get(e.id, []),
        }
        for e in events
    ]


@router.patch("/news/{event_id}", response_model=VisibilityOut)
def hide(
    event_id: str,
    body: VisibilityIn,
    admin: User = Depends(admin_user),
    db: Session = Depends(get_db, scope="function"),
):
    event = db.get(Event, event_id)
    if not event:
        raise AppError(404, "not_found", "Событие не найдено")
    event.visible = body.visible
    audit(db, admin, "news_visibility", event.id, body.model_dump())
    return {"id": event.id, "visible": event.visible}


@router.post("/news/{event_id}/retry", response_model=JobOut, status_code=202)
def retry_news(
    event_id: str, admin: User = Depends(admin_user), db: Session = Depends(get_db, scope="function")
):
    event = db.get(Event, event_id)
    if not event:
        raise AppError(404, "not_found", "Событие не найдено")
    job = enqueue(db, "summarize", {"event_id": event_id}, admin.id, dedup_key=f"summarize:{event_id}")
    event.processing_status = "queued"
    audit(db, admin, "retry_news", event.id)
    return job

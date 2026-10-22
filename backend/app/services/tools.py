"""Read-only tool boundary for Fedor's agent; all calls stay in the authorized company."""

from datetime import date

from sqlalchemy import func, or_, select

from app.errors import AppError
from app.integrations.ai import call_ai
from app.models import BankDocument, Chunk, User
from app.services.access import company_access
from app.services.clients import company_context


class BankRepository:
    def __init__(self, db):
        self._db = db

    def search_chunks(self, query: str, as_of: str, limit: int = 5) -> list[dict]:
        cutoff = date.fromisoformat(as_of).isoformat()
        statement = (
            select(Chunk, BankDocument)
            .join(BankDocument)
            .where(
                BankDocument.status == "done",
                or_(BankDocument.document_date.is_(None), BankDocument.document_date <= cutoff),
            )
        )
        if self._db.bind.dialect.name == "postgresql":
            vector = func.to_tsvector("russian", Chunk.text)
            terms = func.plainto_tsquery("russian", query[:1000])
            statement = statement.where(vector.op("@@")(terms)).order_by(
                func.ts_rank(vector, terms).desc(),
                Chunk.id,
            )
        else:
            statement = statement.where(Chunk.text.contains(query[:1000], autoescape=True)).order_by(Chunk.id)
        return [
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "version": document.version,
                "index_version": document.index_version,
                "filename": document.filename,
                "page": chunk.page,
                "document_date": document.document_date,
                "date_unknown": document.document_date is None,
                "text": chunk.text,
            }
            for chunk, document in self._db.execute(statement.limit(max(1, min(limit, 20))))
        ]


class AnalysisTools:
    def __init__(self, db, user_id, company_id, event_id):
        self._db, self._user_id = db, user_id
        self._company_id, self._event_id = company_id, event_id

    def _authorize(self):
        user = self._db.get(User, self._user_id)
        if not user or user.status != "active":
            raise AppError(403, "forbidden", "Доступ отозван")
        company_access(self._db, user, self._company_id)

    def get_company_context(self, company_id=None):
        self._authorize()
        if company_id is not None and company_id != self._company_id:
            raise AppError(403, "forbidden", "Инструмент ограничен выбранной компанией")
        return company_context(self._db, self._company_id)

    def get_event(self):
        self._authorize()
        from app.services.events import event_context

        return event_context(self._db, self._event_id)

    def search_bank_analytics(self, query: str, as_of: str, limit: int = 5):
        self._authorize()
        date.fromisoformat(as_of)
        return call_ai(
            "search_bank_analytics",
            query=query[:1000],
            as_of=as_of,
            limit=max(1, min(limit, 5)),
            repository=BankRepository(self._db),
        )

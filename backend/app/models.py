from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


def uid() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("system_role IN ('user','admin')"),
        CheckConstraint("status IN ('active','blocked')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    system_role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    group_id: Mapped[str | None] = mapped_column(String(100), index=True)
    profile_version: Mapped[str] = mapped_column(String(64), default="unknown")
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    unknowns: Mapped[list] = mapped_column(JSON, default=list)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    data_semantics_version: Mapped[str] = mapped_column(
        String(64), default="legacy-company-1", server_default="legacy-company-1"
    )
    identity_quality: Mapped[str] = mapped_column(String(16), default="legacy", server_default="legacy")
    client_type: Mapped[str | None] = mapped_column(String(32), index=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id"),
        CheckConstraint("status IN ('pending','active','rejected')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    position_text: Mapped[str] = mapped_column(Text, default="")
    interests: Mapped[list] = mapped_column(JSON, default=list)
    focus_input_hash: Mapped[str | None] = mapped_column(String(64))
    user_focus: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report: Mapped[dict] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PersonLink(Base):
    __tablename__ = "person_links"
    __table_args__ = (UniqueConstraint("person_id", "company_id", "city", "region"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[str] = mapped_column(String(100), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    city: Mapped[str] = mapped_column(String(255), default="")
    region: Mapped[str] = mapped_column(String(255), default="")
    provenance: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")


class ClientRawRow(Base):
    __tablename__ = "client_raw_rows"
    __table_args__ = (UniqueConstraint("batch_id", "file", "row_number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    file: Mapped[str] = mapped_column(String(64))
    row_number: Mapped[int] = mapped_column(Integer)
    entity_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(100))
    raw: Mapped[dict] = mapped_column(JSON)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("batch_id", "row_number"),
        CheckConstraint("amount >= 0 AND payment_count > 0"),
        Index("ix_payments_pair", "payer", "beneficiary"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    payer: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    beneficiary: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(30, 2))
    payment_count: Mapped[int] = mapped_column(Integer)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    classification: Mapped[str] = mapped_column(
        String(16), default="external", server_default="legacy", index=True
    )


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    feed_url: Mapped[str] = mapped_column(Text)
    allowed_hosts: Mapped[list] = mapped_column(JSON)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(255))


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    topics: Mapped[dict] = mapped_column(JSON, default=dict)
    facts: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[str] = mapped_column(String(64), default="1")
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="pending_ai")


class News(Base):
    __tablename__ = "news"
    __table_args__ = (UniqueConstraint("source_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BankDocument(Base):
    __tablename__ = "bank_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(64))
    index_version: Mapped[str] = mapped_column(String(64), default="unindexed")
    document_date: Mapped[str | None] = mapped_column(String(10))
    storage_key: Mapped[str] = mapped_column(String(100))
    page_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[str | None] = mapped_column(Text)


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("page > 0"),
        Index(
            "ix_chunks_russian_text",
            sql_text("to_tsvector('russian'::regconfig, text)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    document_id: Mapped[str] = mapped_column(ForeignKey("bank_documents.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (CheckConstraint("kind IN ('news','bank','company')"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(16))
    source_id: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(64))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    locator: Mapped[dict] = mapped_column(JSON)
    excerpt: Mapped[str] = mapped_column(Text)


class Insight(Base):
    __tablename__ = "insights"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    versions: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FeedSnapshot(Base):
    __tablename__ = "feed_snapshots"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','ready','partial','failed','deferred','stale')"),
        Index("ix_feed_snapshots_owner", "user_id", "company_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    input_key: Mapped[str] = mapped_column(String(64), unique=True)
    versions: Mapped[dict] = mapped_column(JSON)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"))
    error: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedDismissal(Base):
    __tablename__ = "feed_dismissals"
    __table_args__ = (UniqueConstraint("user_id", "company_id", "event_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    version: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("chat_id", "sequence", name="uq_message_chat_sequence"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    chat_id: Mapped[str] = mapped_column(ForeignKey("chats.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','done','failed')"),
        Index("ix_jobs_ready", "status", "available_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"))
    dedup_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[dict | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def enqueued_at(self):
        return self.created_at

    @property
    def ready_at(self):
        return self.finished_at

    @property
    def trace_id(self):
        return self.id


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("insight_id", "user_id"), CheckConstraint("rating IN (-1,1)"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    insight_id: Mapped[str] = mapped_column(ForeignKey("insights.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")


class DemoAction(Base):
    __tablename__ = "demo_actions"
    __table_args__ = (UniqueConstraint("user_id", "company_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    insight_id: Mapped[str | None] = mapped_column(ForeignKey("insights.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    action_type: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(16), default="demo")
    status: Mapped[str] = mapped_column(String(16), default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductEvent(Base):
    __tablename__ = "product_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    insight_id: Mapped[str | None] = mapped_column(ForeignKey("insights.id"))
    event_type: Mapped[str] = mapped_column(String(16))
    session_hash: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(100))
    versions: Mapped[dict] = mapped_column(JSON)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    excluded_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Trace(Base):
    __tablename__ = "traces"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    result: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

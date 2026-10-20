from collections.abc import Generator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine():
    url = get_settings().database_url
    engine = create_engine(
        url,
        pool_pre_ping=True,
        **({"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}),
    )
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

    return engine


def session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with session_factory()() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise

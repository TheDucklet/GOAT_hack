"""Request timing available to synchronous producers without an HTTP dependency."""

from contextvars import ContextVar
from datetime import datetime

received_at: ContextVar[datetime | None] = ContextVar("received_at", default=None)

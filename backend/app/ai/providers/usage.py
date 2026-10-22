import logging
import threading
from pathlib import Path
from typing import Protocol

from app.ai.process_lock import process_lock
from app.ai.providers.models import UsageRecord

logger = logging.getLogger("app.ai.llm")


class UsageSink(Protocol):
    def record(self, entry: UsageRecord) -> None: ...


class LoggingUsageSink:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._lock = threading.Lock()

    def record(self, entry: UsageRecord) -> None:
        logger.info(
            "llm_call request_id=%s task=%s model=%s status=%s input_tokens=%d output_tokens=%d "
            "latency_ms=%d cost_rub=%.6f attempts=%d",
            entry.request_id,
            entry.task,
            entry.model_id,
            entry.status,
            entry.input_tokens,
            entry.output_tokens,
            entry.latency_ms,
            entry.cost_rub,
            entry.attempts,
        )
        if self._path is None:
            return
        with self._lock, process_lock(self._path.with_suffix(self._path.suffix + ".lock")):
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(entry.model_dump_json() + "\n")


class MemoryUsageSink:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    def record(self, entry: UsageRecord) -> None:
        self.records.append(entry)

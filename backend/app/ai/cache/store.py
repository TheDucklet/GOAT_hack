import copy
import json
import os
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.ai.cache.keys import CacheKey
from app.ai.process_lock import process_lock


class CacheStore(Protocol):
    def get(self, key: CacheKey) -> dict | None: ...

    def put(self, key: CacheKey, value: dict) -> None: ...


class MemoryStore:
    def __init__(self, max_items: int = 512) -> None:
        self._items: OrderedDict[str, dict] = OrderedDict()
        self._max_items = max_items
        self._lock = threading.Lock()

    def get(self, key: CacheKey) -> dict | None:
        with self._lock:
            value = self._items.get(key.digest)
            if value is not None:
                self._items.move_to_end(key.digest)
        return copy.deepcopy(value) if value is not None else None

    def put(self, key: CacheKey, value: dict) -> None:
        with self._lock:
            self._items[key.digest] = copy.deepcopy(value)
            self._items.move_to_end(key.digest)
            while len(self._items) > self._max_items:
                self._items.popitem(last=False)


class FileStore:
    def __init__(self, root: Path):
        self._root = root

    def _path(self, key: CacheKey) -> Path:
        return self._root / key.kind / key.digest[:2] / f"{key.digest}.json"

    def lock(self, key: CacheKey):
        return process_lock(self._path(key).with_suffix(".lock"))

    def get(self, key: CacheKey) -> dict | None:
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if entry.get("digest") != key.digest or not isinstance(entry.get("value"), dict):
            return None
        return entry["value"]

    def put(self, key: CacheKey, value: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "digest": key.digest,
            "kind": key.kind,
            "parts": key.parts,
            "created_at": datetime.now(UTC).isoformat(),
            "value": value,
        }
        temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

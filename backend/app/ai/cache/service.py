import threading
from collections import Counter
from collections.abc import Callable
from contextlib import nullcontext
from weakref import WeakValueDictionary

from app.ai.cache.keys import CacheKey
from app.ai.cache.store import CacheStore, MemoryStore


class ResultCache:
    def __init__(self, store: CacheStore | None = None, enabled: bool = True):
        self._store = store or MemoryStore()
        self._enabled = enabled
        self._lock = threading.Lock()
        self._key_locks = WeakValueDictionary()
        self._stats: Counter[str] = Counter()

    def fetch(self, key: CacheKey, compute: Callable[[], dict]) -> tuple[dict, bool]:
        if not self._enabled:
            return self.bypass(key.kind, compute), False
        with self._lock:
            key_lock = self._key_locks.setdefault(key.digest, threading.Lock())
        with key_lock:
            lock = getattr(self._store, "lock", None)
            with lock(key) if lock else nullcontext():
                value = self._store.get(key)
                if value is not None:
                    self._count(key.kind, "hit")
                    return value, True
                self._count(key.kind, "miss")
                value = compute()
                self._store.put(key, value)
                return value, False

    def bypass(self, kind: str, compute: Callable[[], dict]) -> dict:
        self._count(kind, "bypass")
        return compute()

    def _count(self, kind: str, outcome: str) -> None:
        with self._lock:
            self._stats[f"{kind}.{outcome}"] += 1

    def stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

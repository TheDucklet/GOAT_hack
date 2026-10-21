import hashlib
import json
from dataclasses import dataclass


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def digest_of(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    kind: str
    parts: dict
    digest: str


def make_key(kind: str, **parts) -> CacheKey:
    return CacheKey(kind=kind, parts=parts, digest=digest_of([kind, parts]))


def focus_hash(user_focus: dict) -> str:
    return digest_of(user_focus)

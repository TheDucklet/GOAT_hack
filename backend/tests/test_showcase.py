import json

import pytest
from sqlalchemy import func, select

from app.db import session_factory
from app.models import Company, Evidence, Job, Membership, News, User
from app.services.sessions import hasher
from app.services.showcase import FIXTURE, seed_showcase
from tests.factories import PASSWORD


def test_showcase_is_idempotent_and_never_calls_ai_by_default(env):
    with session_factory()() as db, db.begin():
        first = seed_showcase(db, PASSWORD)
        second = seed_showcase(db, "Another-password-2026")
        assert first == second
        assert len(first["accounts"]) == 4
        assert {a["company_id"] for a in first["accounts"]} == {"showcase_metal", "showcase_build"}
        assert len({a["position"] for a in first["accounts"]}) == 2
        assert db.scalar(select(func.count()).select_from(Job)) == 0
        assert db.scalar(select(func.count()).select_from(News)) == 1
        assert db.scalar(select(func.count()).select_from(Evidence).where(Evidence.kind == "news")) == 1
        for account in first["accounts"]:
            user = db.scalar(select(User).where(User.email == account["email"]))
            assert hasher.verify(user.password_hash, PASSWORD)
            membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
            assert membership.status == "active"
        metal = db.get(Company, "showcase_metal")
        build = db.get(Company, "showcase_build")
        assert metal.features["CL_PRODUCT_LOA_MARK"]["value"] == "1"
        assert build.features["CL_PRODUCT_LOA_MARK"]["value"] == "0"
        assert all(f["provenance"]["synthetic"] for f in metal.features.values())


def test_unseen_phase_is_separate_and_paid_queue_requires_flag(env):
    with session_factory()() as db, db.begin():
        seed_showcase(db, PASSWORD)
        assert db.scalar(select(func.count()).select_from(News)) == 1
        unseen = seed_showcase(db, PASSWORD, phase="unseen", enqueue_ai=True)
        repeated = seed_showcase(db, PASSWORD, phase="unseen", enqueue_ai=True)
        assert unseen == repeated
        assert db.scalar(select(func.count()).select_from(News)) == 2
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert unseen["events"][0]["job_id"] is not None


@pytest.mark.parametrize("kind", ["company", "user", "admin"])
def test_showcase_refuses_to_overwrite_or_elevate_existing_records(env, kind):
    with session_factory()() as db, db.begin():
        if kind == "company":
            db.add(Company(id="showcase_metal", name="Existing company", profile_version="real-import"))
        elif kind == "user":
            db.add(User(email="showcase_metal.accountant@goat.example.org", password_hash="untouched"))
        else:
            admin = db.scalar(select(User).where(User.email == "admin@goat.example.org"))
            admin.system_role = "user"
        db.flush()
        with pytest.raises(ValueError):
            seed_showcase(db, PASSWORD)


def test_demo_publications_keep_benchmark_source_dates_and_paraphrases():
    from pathlib import Path

    corpus = Path(__file__).parents[2] / "docs/quality/benchmark/events.json"
    if not corpus.exists():
        pytest.skip("Source provenance cross-check runs in the repository checkout")
    originals = json.loads(corpus.read_text(encoding="utf-8"))["events"]
    for event in json.loads(FIXTURE.read_text(encoding="utf-8"))["events"]:
        original = next(e for e in originals if e.get("url") == event["url"])
        assert event["text"] == original["text"]
        assert event["published_at"] == original["published_at"]


def test_showcase_requires_a_nontrivial_explicit_password(env):
    with session_factory()() as db, db.begin():
        with pytest.raises(ValueError, match="DEMO_PASSWORD"):
            seed_showcase(db, "short")

import os

import pytest
from fastapi.testclient import TestClient

from app.cli import seed_demo
from app.config import get_settings
from app.db import Base, get_engine, session_factory
from app.main import create_app

PASSWORD = "Synthetic-Test-Password-2026"


@pytest.fixture
def env(tmp_path, monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'goat_test.db'}")
    if not url.startswith("sqlite") and (not url.split("?")[0].endswith("/goat_test")):
        raise RuntimeError("Tests may only recreate the explicitly named goat_test database")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("AI_MODULE", "")
    get_settings.cache_clear()
    get_engine.cache_clear()
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with session_factory()() as db, db.begin():
        seed_demo(db, PASSWORD)
    yield tmp_path
    engine.dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def client(env):
    with TestClient(create_app()) as client:
        yield client


def login(client, name="user_a"):
    result = client.post("/auth/login", json={"email": f"{name}@goat.example.org", "password": PASSWORD})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()

import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.ai.cache.calls import CacheSettings
from app.ai.evaluation.demo import write_demo
from app.ai.ocr.settings import OcrSettings
from app.ai.promptdocs import DEFAULT_DIRECTORY, PROMPTS, main
from app.ai.providers.models import ALLOWED_MODEL_IDS
from app.ai.providers.settings import DEFAULT_TASK_MODELS, LLMSettings
from app.ai.rag.chunking import ChunkSettings

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "backend" / "app" / "ai" / "README.md"
NOTICES = ROOT / "docs" / "notices" / "ai.md"
DEMO = ROOT / "docs" / "demo" / "agent-trace.json"
ACCEPTANCE = ROOT / "docs" / "quality" / "acceptance"
CHUNKS = ROOT / "docs" / "ai" / "fixtures" / "bank-chunks.json"


def test_prompt_files_match_the_code():
    assert main(["check", "--directory", str(DEFAULT_DIRECTORY)]) == 0


def test_every_task_has_a_prompt_file_and_a_default_model():
    assert {doc.task for doc in PROMPTS} == set(DEFAULT_TASK_MODELS)
    assert all((DEFAULT_DIRECTORY / doc.file).is_file() for doc in PROMPTS)
    assert set(DEFAULT_TASK_MODELS.values()) <= ALLOWED_MODEL_IDS


def test_outdated_prompt_file_is_reported(tmp_path):
    main(["write", "--directory", str(tmp_path)])
    first = tmp_path / PROMPTS[0].file
    first.write_text(first.read_text(encoding="utf-8") + "\nизменение\n", encoding="utf-8")
    assert main(["check", "--directory", str(tmp_path)]) == 1


def test_prompt_files_carry_no_secrets_or_client_data():
    for path in DEFAULT_DIRECTORY.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", text)
        assert not re.search(r"U_\d+", text)


def environment_names() -> set[str]:
    names = {"AI_MODULE", "AI_GENERATION_VERSION"}
    for settings, prefix in (
        (LLMSettings, "AI_"),
        (OcrSettings, "AI_OCR_"),
        (CacheSettings, "AI_CACHE_"),
        (ChunkSettings, "AI_RAG_"),
    ):
        names |= {prefix + field.upper() for field in settings.model_fields}
    return names


def test_readme_lists_every_environment_variable():
    text = README.read_text(encoding="utf-8")
    missing = sorted(name for name in environment_names() if f"`{name}`" not in text)
    assert not missing, missing


def test_readme_commands_point_to_existing_modules():
    text = README.read_text(encoding="utf-8")
    modules = set(re.findall(r"python -m (app\.ai[\w.]*)", text))
    assert modules
    for module in modules:
        assert importlib.util.find_spec(module) is not None, module


def test_readme_lists_every_allowed_model():
    text = README.read_text(encoding="utf-8")
    assert all(f"`{model}`" in text for model in ALLOWED_MODEL_IDS)


def test_notices_cover_every_allowed_model_with_a_license():
    text = NOTICES.read_text(encoding="utf-8")
    for model in ALLOWED_MODEL_IDS:
        row = next(line for line in text.splitlines() if f"`{model}`" in line)
        assert re.search(r"Apache-2\.0|MIT", row), model


def test_notices_do_not_contain_keys():
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", NOTICES.read_text(encoding="utf-8"))


@pytest.mark.skipif(not (ACCEPTANCE / "S7.json").exists(), reason="результат приёмки не записан")
def test_demo_trace_shows_retry_search_with_page_and_quote():
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    kinds = [step["step"] for step in demo["steps"]]
    assert "retry" in kinds and kinds[-1] == "stop"
    assert any(step["purpose"] == "retry" for step in demo["steps"] if step["step"] == "search")
    for claim in demo["bank_view"]:
        assert claim["evidence"]
        for source in claim["evidence"]:
            assert source["page"] >= 1 and source["document"].endswith(".pdf") and source["excerpt"]


@pytest.mark.skipif(not (ACCEPTANCE / "S7.json").exists(), reason="результат приёмки не записан")
def test_demo_trace_is_reproducible_from_the_saved_acceptance(tmp_path):
    output = tmp_path / "agent-trace.json"
    write_demo(ACCEPTANCE, CHUNKS, output)
    assert json.loads(output.read_text(encoding="utf-8")) == json.loads(DEMO.read_text(encoding="utf-8"))

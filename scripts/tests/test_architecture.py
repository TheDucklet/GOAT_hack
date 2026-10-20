"""Negative controls: architecture checks must fail for invalid project layouts."""

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

spec = importlib.util.spec_from_file_location(
    "architecture", Path(__file__).resolve().parents[1] / "check_architecture.py"
)
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


class ArchitectureChecks(unittest.TestCase):
    def test_cycles_are_rejected(self):
        self.assertTrue(architecture.cycles({"a": {"b"}, "b": {"a"}}))
        self.assertEqual(architecture.cycles({"a": {"b"}, "b": set()}), [])

    def test_domain_cannot_import_http_even_inside_a_function(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "backend/app/services/example.py"
            service.parent.mkdir(parents=True)
            service.write_text("def operation():\n    from app.api import companies\n", encoding="utf-8")
            _, violations = architecture.backend_graph(root)
            self.assertTrue(any("Domain/AI depends on HTTP/runtime" in item for item in violations))

    def test_duplicate_dependencies_and_lock_drift_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            (root / "frontend").mkdir()
            (root / "backend/pyproject.toml").write_text(
                '[project]\ndependencies=["httpx==1"]\n[project.optional-dependencies]\ndev=["httpx==1"]\n',
                encoding="utf-8",
            )
            (root / "backend/requirements.lock").write_text("httpx==2\n", encoding="utf-8")
            (root / "frontend/package.json").write_text("{}", encoding="utf-8")
            (root / "frontend/package-lock.json").write_text(
                json.dumps({"packages": {"": {}}}), encoding="utf-8"
            )
            violations = architecture.dependency_violations(root)
            self.assertTrue(any("declared more than once" in item for item in violations))
            self.assertTrue(any("Manifest/lock version mismatch" in item for item in violations))


if __name__ == "__main__":
    unittest.main()

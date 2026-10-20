"""Check backend import boundaries, cycles and declared dependency ownership.

Standard library only. Run from any directory; generated contracts/lock files
remain artifacts, while pyproject.toml/package.json declare direct dependencies.
"""

import argparse
import ast
import json
import re
import tomllib
from pathlib import Path


def backend_graph(root):
    app = root / "backend/app"
    modules = {}
    for path in app.rglob("*.py"):
        parts = list(path.relative_to(app.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    graph = {name: set() for name in modules}
    violations = []
    for name, path in modules.items():
        package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = package.split(".")[: len(package.split(".")) - node.level + 1] if node.level else []
                base = ".".join(prefix + ([node.module] if node.module else []))
                targets = [base]
                targets.extend(
                    f"{base}.{alias.name}" for alias in node.names if f"{base}.{alias.name}" in modules
                )
            for target in targets:
                if target in modules and target != name:
                    graph[name].add(target)
                if name.startswith(("app.services.", "app.integrations.")) and target.startswith(
                    ("app.api", "app.main", "app.worker", "app.security", "fastapi", "starlette")
                ):
                    violations.append(f"Domain/AI depends on HTTP/runtime: {name} -> {target}")
                if name in {
                    "app.config",
                    "app.db",
                    "app.models",
                    "app.schemas",
                    "app.errors",
                } and target.startswith(
                    ("app.api", "app.services", "app.integrations", "app.worker", "app.security")
                ):
                    violations.append(f"Shared core depends on a higher layer: {name} -> {target}")
                if name.startswith("app.api.") and target in {
                    "app.worker",
                    "app.services.jobs",
                    "app.services.scheduling",
                }:
                    violations.append(f"HTTP producer depends on worker runtime: {name} -> {target}")
    return graph, violations


def cycles(graph):
    visiting, finished, stack, found = set(), set(), [], []

    def visit(name):
        if name in visiting:
            found.append(" -> ".join(stack[stack.index(name) :] + [name]))
            return
        if name in finished:
            return
        visiting.add(name)
        stack.append(name)
        for target in sorted(graph.get(name, ())):
            visit(target)
        stack.pop()
        visiting.remove(name)
        finished.add(name)

    for name in sorted(graph):
        visit(name)
    return found


def dependency_violations(root):
    project = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = {}

    def normalize(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    def requirement(value):
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?==([^;\s]+)", value.strip())
        if not match:
            raise ValueError(f"Expected a pinned direct dependency: {value}")
        return normalize(match[1]), match[2]

    issues = []
    for line in (root / "backend/requirements.lock").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, version = requirement(line)
        if name in lock:
            issues.append(f"Duplicate lock entry: {name}")
        lock[name] = version
    owned = {}
    groups = {"runtime": project["dependencies"], **project.get("optional-dependencies", {})}
    for group, values in groups.items():
        for value in values:
            name, version = requirement(value)
            if name in owned:
                issues.append(f"Dependency declared more than once: {name} ({owned[name]}, {group})")
            owned[name] = group
            if lock.get(name) != version:
                issues.append(f"Manifest/lock version mismatch: {name}")
    frontend = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    frontend_lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for group in ["dependencies", "devDependencies"]:
        if frontend.get(group, {}) != frontend_lock["packages"][""].get(group, {}):
            issues.append(f"Frontend manifest/lock mismatch: {group}")
    repeated = set(frontend.get("dependencies", {})) & set(frontend.get("devDependencies", {}))
    issues.extend(f"Frontend dependency declared in runtime and dev: {name}" for name in sorted(repeated))
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    graph, violations = backend_graph(root)
    violations += [f"Import cycle: {cycle}" for cycle in cycles(graph)]
    violations += dependency_violations(root)
    result = {
        "result": "FAIL" if violations else "PASS",
        "backend_modules": len(graph),
        "backend_import_edges": sum(map(len, graph.values())),
        "violations": violations,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(violations))


if __name__ == "__main__":
    main()

"""Export the committed submission as a ZIP with a resolved SHA and SHA-256 manifest.

Standard library only. Refuses a dirty checkout and a tag pointing elsewhere.
Ignored env files, data and local credentials never enter git archive.
"""

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from html import escape
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/release"))
    parser.add_argument("--tag", help="Existing tag that must resolve to HEAD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    def git(*command):
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={root.as_posix()}", *command], cwd=root,
        )

    if git("status", "--porcelain").strip():
        parser.error("Commit all submission changes before exporting")
    sha = git("rev-parse", "HEAD").decode().strip()
    if args.tag:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*", args.tag):
            parser.error("Invalid tag")
        if git("rev-parse", f"refs/tags/{args.tag}^{{commit}}").decode().strip() != sha:
            parser.error("Tag must resolve to HEAD")
    output = args.output_dir.resolve()
    if output == root or not output.is_relative_to(root / "artifacts"):
        parser.error("Use an output directory below this checkout's ignored artifacts directory")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"GOAT_hack-{sha[:12]}.zip"
    git("archive", "--format=zip", f"--output={archive}", "HEAD")
    files = {}
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.endswith("/"):
                continue
            parts = Path(name).parts
            if (any(p in {".local", "storage", "artifacts", "node_modules", ".git"} for p in parts)
                    or (Path(name).name.startswith(".env")
                        and Path(name).name not in {".env.example", ".env.ai.example"})):
                raise SystemExit(f"Private runtime path in tracked archive: {name}")
            files[name] = hashlib.sha256(bundle.read(name)).hexdigest()
    manifest = {
        "schema_version": 1, "generated_at": datetime.now(UTC).isoformat(),
        "repository": "https://github.com/TheDucklet/GOAT_hack", "commit": sha,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(), "tag": args.tag,
        "service_url": "https://shenti.space", "archive": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "file_count": len(files), "files_sha256": files,
        "readiness": "submission candidate; see docs/release/STATUS.md for acceptance limits",
        "release_metadata": json.loads((root / "docs/release/submission.json").read_text(encoding="utf-8")),
    }
    cover = f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>GOAT_hack — версия для сдачи</title>
<style>@page{{size:A4;margin:20mm}}body{{font:16px/1.55 Arial,sans-serif;color:#172033;max-width:760px;margin:40px auto}}
h1{{font-size:34px}}h2{{font-size:20px;margin-top:28px}}a{{color:#b51d2c}}code{{font-size:13px;overflow-wrap:anywhere}}
.note{{font-size:13px;color:#4d5668}}@media print{{body{{margin:0}}}}</style>
<h1>GOAT_hack</h1><p>Персональная бизнес-аналитика: новость → контекст компании и должности →
обоснованный инсайт → источники → уточнение в AI-чате.</p>
<h2>Репозиторий с историей</h2><p><a href="{manifest['repository']}">{manifest['repository']}</a></p>
<p>Точная версия: <code>{sha}</code><br>
<a href="{manifest['repository']}/tree/{sha}">Открыть код этой версии</a> ·
<a href="{manifest['repository']}/blob/{sha}/README.md">Развёртывание и испытания (README)</a></p>
<h2>Работающий прототип</h2><p><a href="{manifest['service_url']}">{manifest['service_url']}</a></p>
<p>Для локального запуска: Docker Compose; четыре сервиса, синтетические компании и аккаунты.
Для реальных AI-ответов нужны серверный ключ и согласованный бюджет; для позиции банка — подготовленный корпус PDF.</p>
<h2>Сценарий и материалы</h2><p>
<a href="{manifest['repository']}/blob/{sha}/docs/demo/runbook.md">Полный пользовательский путь и матрица 2×2</a><br>
<a href="{manifest['repository']}/blob/{sha}/docs/release/presentation.pdf">Презентация PDF</a><br>
<a href="{manifest['repository']}/blob/{sha}/docs/release/STATUS.md">Статус приёмки, метрики и ограничения</a></p>
<p class="note">Альфа-Бизнес/SSO и обращение к менеджеру смоделированы; запрос в банк не отправляется.
Общий F-16/R-11 не объявлен принятым. SHA VPS проверяется отдельно оператором, ссылка на стенд не удостоверяет версию.
Секреты и PDF/CSV организаторов не включены в исходники. Demo-доступы оператор передаёт отдельно.</p>
<p class="note">Архив: {escape(archive.name)}<br>SHA-256: <code>{manifest['archive_sha256']}</code><br>
Сформировано: {escape(manifest['generated_at'])}. Отправку организаторам выполняет Роман.</p></html>"""
    (output / "submission.html").write_text(cover + "\n", encoding="utf-8")
    manifest["submission_html"] = "submission.html"
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["commit", "tag", "archive", "archive_sha256", "file_count"]}))


if __name__ == "__main__":
    main()

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
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ["commit", "tag", "archive", "archive_sha256", "file_count"]}))


if __name__ == "__main__":
    main()

"""A-01 schema operations; business commands are implemented in subsequent tasks."""

import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config


def migrate():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")


def export_openapi(output: Path):
    from app.main import create_app

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "export-openapi"])
    parser.add_argument("--output", type=Path, default=Path("../docs/contracts/openapi.json"))
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
    else:
        export_openapi(args.output)


if __name__ == "__main__":
    main()

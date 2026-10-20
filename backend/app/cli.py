import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import get_settings
from app.db import session_factory
from app.models import Company, Membership, User
from app.security import hasher
from app.services.clients import import_clients


def migrate():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "head")


def create_admin(db, email, password):
    if len(password) < 10:
        raise ValueError("Admin password must contain at least 10 characters")
    if db.scalar(select(User.id).where(User.email == email.lower())):
        raise ValueError("Email already exists; use the audited admin API for existing users")
    db.add(User(email=email.lower(), password_hash=hasher.hash(password), system_role="admin"))


def seed_demo(db, password):
    if len(password) < 10:
        raise ValueError("Set DEMO_PASSWORD to at least 10 characters")
    for suffix, loan in [("a", "1.0"), ("b", "0.0")]:
        company_id = f"demo_company_{suffix}"
        if not db.get(Company, company_id):
            values = {
                "MAINOKVED_CODE": "25.61",
                "MAINOKVED_NAME": "Обработка металлов",
                "REGION": "Москва" if suffix == "a" else "Татарстан",
                "CL_PRODUCT_LOA_MARK": loan,
            }
            db.add(
                Company(
                    id=company_id,
                    name=f"Демо компания {suffix.upper()}",
                    profile_version="demo-v1",
                    features={
                        field: {"value": value, "source": {"file": "synthetic-demo", "field": field}}
                        for field, value in values.items()
                    },
                    unknowns=["loan_amount", "loan_rate"],
                )
            )
    db.flush()
    for name in ["user_a", "user_b", "admin"]:
        email = f"{name}@goat.example.org"
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            user = User(
                email=email,
                password_hash=hasher.hash(password),
                system_role="admin" if name == "admin" else "user",
            )
            db.add(user)
            db.flush()
        if name != "admin":
            company_id = f"demo_company_{name[-1]}"
            if not db.scalar(
                select(Membership.id).where(
                    Membership.user_id == user.id, Membership.company_id == company_id
                )
            ):
                db.add(
                    Membership(
                        user_id=user.id,
                        company_id=company_id,
                        status="active",
                        position_text="Главный бухгалтер",
                        interests=[],
                    )
                )


def export_openapi(output: Path):
    from app.main import create_app

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description="GOAT backend operations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate")
    export = commands.add_parser("export-openapi")
    export.add_argument("--output", type=Path, default=Path("../docs/contracts/openapi.json"))
    admin = commands.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    commands.add_parser("seed-demo")
    clients = commands.add_parser("import-clients")
    clients.add_argument("--directory", type=Path, required=True)
    clients.add_argument("--report", type=Path, default=Path("../docs/data/import-report.json"))
    args = parser.parse_args()
    if args.command == "migrate":
        migrate()
        return
    if args.command == "export-openapi":
        export_openapi(args.output)
        return
    with session_factory()() as db, db.begin():
        if args.command == "create-admin":
            secret = get_settings().admin_password
            create_admin(db, args.email, secret.get_secret_value() if secret else "")
        elif args.command == "seed-demo":
            secret = get_settings().demo_password
            seed_demo(db, secret.get_secret_value() if secret else "")
        elif args.command == "import-clients":
            report = import_clients(db, args.directory)
    if args.command == "import-clients":
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in report.items() if k != "conflicts"}, ensure_ascii=False))


if __name__ == "__main__":
    main()

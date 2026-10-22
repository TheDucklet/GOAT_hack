from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.db import get_engine


def test_runtime_upgrade_preserves_existing_records_and_job_constraint(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(config, "0003")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id,email,password_hash,system_role,status,created_at) VALUES ('u','synthetic@example.org','hash','user','active',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO companies (id,name,profile_version,features,unknowns,is_placeholder) VALUES ('c','Synthetic','old','{}','[]',0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO events (id,title,normalized_title,topics,facts,version,visible,processing_status) VALUES ('e','Synthetic','synthetic','{}','[]','1',1,'done')"
            )
        )
        connection.execute(
            text("INSERT INTO chats (id,user_id,company_id,event_id) VALUES ('chat','u','c','e')")
        )
        connection.execute(
            text(
                "INSERT INTO messages (id,chat_id,sequence,role,text,created_at) VALUES ('m','chat',1,'user','Synthetic preserved history',CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bank_documents (id,filename,sha256,version,index_version,storage_key,page_count,status) VALUES ('d','synthetic.pdf','sha','v','i','stored.pdf',1,'done')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO jobs (id,kind,status,payload,attempts,available_at,created_at) VALUES ('j','focus','done','{}',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT text FROM messages WHERE id='m'")) == "Synthetic preserved history"
        )
        assert connection.scalar(text("SELECT storage_key FROM bank_documents WHERE id='d'")) == "stored.pdf"
        assert connection.scalar(text("SELECT count(*) FROM users")) == 1
        assert connection.scalar(text("SELECT received_at = created_at FROM jobs WHERE id='j'")) == 1
    assert any("status" in row["sqltext"] for row in inspect(engine).get_check_constraints("jobs"))
    command.check(config)
    engine.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()

"""Live paid A17 acceptance. Requires an explicitly named isolated Compose stack.

Keys are read only by the server from ignored .env.ai. Output contains no prompts.
"""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, choices=["goat-a17-local"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8085/api")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = {
        "kind": "real paid gateway with live RSS, PostgreSQL tools and persistent Compose volumes",
        "started_at": datetime.now(UTC).isoformat(),
        "checks": [],
        "result": "RUNNING",
    }

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def compose(*command):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                args.project,
                "-f",
                "compose.yaml",
                "-f",
                "compose.acceptance.yaml",
                *command,
            ],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if result.returncode:
            raise RuntimeError(f"Compose {command[0]} failed with code {result.returncode}")
        return result.stdout

    client = httpx.Client(base_url=args.base_url, timeout=30)

    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code} {path}")
        return response.json() if response.content else None

    def check(name, value):
        if not value:
            raise AssertionError(name)
        report["checks"].append({"check": name, "result": "PASS"})
        print("PASS " + name, flush=True)
        save()

    def login(name):
        session = request(
            "POST",
            "/auth/login",
            json={"email": name + "@goat.example.org", "password": "Local-demo-password-2026"},
        )
        client.headers["X-CSRF-Token"] = session["csrf_token"]

    def wait_job(job_id):
        until = time.monotonic() + 600
        while time.monotonic() < until:
            value = request("GET", "/jobs/" + job_id)
            if value["status"] in {"done", "failed"}:
                report.setdefault("jobs", []).append(value)
                save()
                return value
            time.sleep(1)
        raise TimeoutError("bounded acceptance wait expired")

    try:
        compose("exec", "-T", "api", "python", "-m", "app.cli", "seed-demo")
        login("admin")
        report["budget_before"] = request("GET", "/admin/runtime-metrics")["budget"]
        if args.pdf:
            uploaded = request(
                "POST",
                "/admin/documents",
                files={"file": ("runtime-bank-extract.pdf", args.pdf.read_bytes(), "application/pdf")},
            )
            report["document"] = uploaded
            job_id = (uploaded.get("job") or {}).get("id")
            check(
                "bank PDF processed by real worker",
                uploaded["document"]["status"] == "done" or wait_job(job_id)["status"] == "done",
            )
        collection = request("POST", "/admin/jobs/collect-news")
        check("news collection entered through API and queue", wait_job(collection["id"])["status"] == "done")
        news = json.loads(
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from app.db import session_factory; from app.models import News,Job; from sqlalchemy import select; import json; db=session_factory()(); n=db.scalar(select(News).order_by(News.fetched_at.desc()).limit(1)); assert n; j=db.scalar(select(Job).where(Job.kind=='summarize',Job.payload['event_id'].as_string()==n.event_id).order_by(Job.created_at.desc())); assert j; print(json.dumps(dict(event_id=n.event_id,source=n.source_id,job_id=j.id,url=n.url,kind='live public RSS')))",
            )
        )
        report["publication"] = news
        check("live news summarized by configured AI bridge", wait_job(news["job_id"])["status"] == "done")
        login("user_a")
        start = time.perf_counter()
        queued = request("GET", "/companies/demo_company_a/feed?contract_version=v2")
        check("GET queues bounded feed preparation", queued["generation_status"] == "queued")
        job = wait_job(queued["job_id"])
        report["cold_prepare_seconds"] = round(time.perf_counter() - start, 3)
        prepared = request(
            "GET", "/companies/demo_company_a/feed?contract_version=v2&snapshot_id=" + queued["snapshot_id"]
        )
        ready = [item for item in prepared["items"] if item["generation_status"] == "ready"]
        report["feed"] = {
            key: prepared[key]
            for key in ("snapshot_id", "generation_status", "versions", "ready_at", "job_id")
        }
        check("real LLM produces a persisted ready v2 card", job["status"] == "done" and len(ready) == 1)
        card = request("GET", "/insights/" + ready[0]["insight_id"])
        report["insight"] = {
            "id": card["id"],
            "trace_id": card["result"]["trace_id"],
            "schema_version": card["result"]["schema_version"],
        }
        start = time.perf_counter()
        repeated = request("POST", "/companies/demo_company_a/insights", json={"event_id": news["event_id"]})
        report["warm_read_seconds"] = round(time.perf_counter() - start, 3)
        check("build_insight endpoint reuses matching persisted card", repeated["id"] == card["id"])
        chat = request("POST", "/chats", json={"company_id": "demo_company_a", "event_id": news["event_id"]})
        question = request(
            "POST",
            "/chats/" + chat["id"] + "/messages",
            json={"text": "Почему эта новость важна для выбранной компании?"},
        )
        check("chat processed by real AI worker", wait_job(question["id"])["status"] == "done")
        messages = request("GET", "/chats/" + chat["id"] + "/messages")
        report["chat"] = {"id": chat["id"], "message_count": len(messages)}
        check("assistant answer saved", any(item["role"] == "assistant" for item in messages))
        login("admin")
        before = request("GET", "/admin/runtime-metrics")
        report["runtime_before_recreate"] = before
        identity = json.loads(
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "from pathlib import Path; import json,hashlib; p=Path('/srv/backend/storage/ai/cache'); print(json.dumps(sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.json'))))",
            )
        )
        compose("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180")
        after = request("GET", "/admin/runtime-metrics")
        report["runtime_after_recreate"] = after
        check(
            "spent budget survives recreation",
            after["budget"]["spent_rub"] == before["budget"]["spent_rub"] > 0,
        )
        restored = json.loads(
            compose(
                "exec",
                "-T",
                "worker",
                "python",
                "-c",
                "from pathlib import Path; import json,hashlib; p=Path('/srv/backend/storage/ai/cache'); print(json.dumps(sorted(hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.json'))))",
            )
        )
        check("cache identity survives recreation and is shared", bool(identity) and identity == restored)
        login("user_a")
        check(
            "ready card remains readable after recreation",
            request("GET", "/insights/" + card["id"])["id"] == card["id"],
        )
        check(
            "chat history survives recreation",
            len(request("GET", "/chats/" + chat["id"] + "/messages")) == len(messages),
        )
        report["result"] = "PASS"
    except Exception as error:
        report["result"] = "FAIL"
        report["error"] = str(error)
        print(type(error).__name__ + ": " + str(error), flush=True)
    finally:
        client.close()
        report["finished_at"] = datetime.now(UTC).isoformat()
        save()
    raise SystemExit(0 if report["result"] == "PASS" else 1)


if __name__ == "__main__":
    main()

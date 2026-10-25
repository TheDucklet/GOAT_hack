"""R13 browser acceptance over real HTTP/PostgreSQL/worker, synthetic AI only."""

import argparse
import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8094")
    parser.add_argument("--channel", default="msedge")
    parser.add_argument("--output", type=Path, default=Path("artifacts/r13/browser"))
    args = parser.parse_args()
    if not args.project.startswith("goat-r13-") or urlsplit(
        args.base_url
    ).hostname not in {"localhost", "127.0.0.1"}:
        parser.error("Use an isolated local R13 project")
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    report = {
        "result": "RUNNING",
        "mode": "synthetic_AI_real_HTTP_PostgreSQL_worker",
        "paid_model_calls": 0,
        "checks": [],
    }
    environment = {
        **os.environ,
        "IMAGE_TAG": "r13-check",
        "AI_ENV_FILE": ".env.ai.example",
        "DOCKER_CONTEXT": "desktop-linux",
    }
    compose = [
        "docker",
        "compose",
        "-p",
        args.project,
        "-f",
        "compose.yaml",
        "-f",
        "frontend/tests/compose.r13.yaml",
    ]

    def fixture(action):
        value = subprocess.run(
            compose
            + [
                "exec",
                "-T",
                "api",
                "python",
                "/srv/r13/prepared_feed_fixture.py",
                action,
            ],
            cwd=root,
            env=environment,
            input=json.dumps({"password": password}) if action == "seed" else "",
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        if value.returncode:
            raise RuntimeError("Fixture failed: " + value.stderr)

    def passed(name):
        report["checks"].append({"check": name, "result": "PASS"})
        print("PASS " + name, flush=True)

    fixture("seed")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        requests, errors = [], []
        page.on(
            "request",
            lambda request: requests.append(
                (
                    request.method,
                    urlsplit(request.url).path,
                    urlsplit(request.url).query,
                )
            ),
        )
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        try:
            page.goto(args.base_url + "/app/analytics")
            page.get_by_label("Email", exact=True).fill("user_a@goat.example.org")
            page.get_by_label("Пароль", exact=True).fill(password)
            page.get_by_role("button", name="Войти", exact=True).click()
            feed = page.get_by_role("region", name="Персональная лента", exact=True)
            summary_a = (
                "Учебный кредит с плавающей ставкой требует пересмотра плана платежей."
            )
            summary_b = (
                "Недостаточно данных для оценки процентного влияния на компанию."
            )
            expect(feed.locator(".feed-personal-summary")).to_contain_text(
                summary_a, timeout=60_000
            )
            expect(
                feed.get_by_text(
                    "До ближайшего пересмотра учебного договора", exact=False
                )
            ).to_be_visible()
            expect(feed.get_by_role("note")).to_contain_text(
                "не являются официальной позицией банка"
            )
            assert not any(
                "/insights/" in path
                or (method == "POST" and path.endswith("/insights"))
                for method, path, _ in requests
            )
            assert any(
                "contract_version=v2" in query and "snapshot_id=" in query
                for _, path, query in requests
                if path.endswith("/feed")
            )
            passed(
                "queued snapshot is polled by id; personalized meaning/mechanism/impact/horizon appear without N card requests or generation POSTs"
            )
            expect(feed.get_by_text("Подготовка отложена", exact=True)).to_be_visible()
            expect(
                feed.get_by_text(
                    "Исходная учебная новость, не персональный вывод."
                ).first
            ).not_to_be_visible()
            passed(
                "deferred analysis stays distinct from ready preview; raw summary is only a collapsed news source"
            )
            feed.get_by_role("button", name="Основание 1", exact=True).first.click()
            expect(
                feed.get_by_role("link", name="Первоисточник · example.org ↗")
            ).to_be_visible()
            passed("preview evidence resolves lazily through the authorized source API")
            feed.get_by_role(
                "button", name="Учебное изменение ставки", exact=True
            ).click()
            panel = page.get_by_role("region", name="Анализ события", exact=True)
            expect(panel.locator(".insight-content")).to_be_visible(timeout=15_000)
            assert (
                sum(
                    bool(re.fullmatch("/api/insights/[^/]+", path))
                    for _, path, _ in requests
                )
                == 1
            )
            assert not any(
                method == "POST" and path.endswith("/insights")
                for method, path, _ in requests
            )
            passed(
                "opening detail reads the same persisted insight exactly once without rebuilding"
            )
            page.screenshot(path=str(args.output / "desktop.png"), full_page=True)
            await_b = page.get_by_role("combobox", name="Компания", exact=True)
            await_b.select_option("demo_company_b")
            expect(feed.locator(".feed-personal-summary")).to_contain_text(
                summary_b, timeout=60_000
            )
            expect(
                feed.get_by_text("Влияние: Недостаточно данных", exact=True)
            ).to_be_visible()
            expect(
                page.get_by_text(
                    "В учебном профиле подтверждён плавающий кредит;", exact=False
                )
            ).not_to_be_visible()
            assert panel.get_attribute("data-event-id") is None
            passed(
                "same event has a supported synthetic debt mechanism in company A and explicit uncertainty in B; switching clears the workspace"
            )
            await_b.select_option("demo_company_a")
            expect(feed.locator(".feed-personal-summary")).to_contain_text(
                summary_a, timeout=30_000
            )
            fixture("stale")
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            expect(feed.locator(".feed-personal-summary")).to_have_count(
                0, timeout=15_000
            )
            expect(
                feed.get_by_text(
                    "Предыдущий персональный вывод скрыт.", exact=False
                ).first
            ).to_be_visible()
            feed.get_by_role("button", name="Обновить ленту", exact=True).click()
            expect(feed.locator(".feed-personal-summary")).to_contain_text(
                summary_a, timeout=60_000
            )
            passed(
                "version check removes stale previews; explicit refresh prepares a new snapshot through the worker"
            )
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            expect(feed.get_by_role("note")).to_be_visible()
            page.screenshot(path=str(args.output / "mobile.png"), full_page=True)
            passed(
                "390px feed keeps personalized content, source controls and notice without overflow"
            )
            assert not errors, errors
            report["result"] = "PASS"
        finally:
            if report["result"] != "PASS":
                report["result"] = "FAIL"
                page.screenshot(path=str(args.output / "failure.png"), full_page=True)
            (args.output / "report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            browser.close()
    return 0


if __name__ == "__main__":
    main()

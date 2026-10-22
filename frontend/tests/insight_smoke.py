"""R05 browser → real API/PG/worker; saved synthetic examples and synthetic AI only.

No HTTP interception, no paid gateway, no actual bank/client documents.
Start compose.yaml + frontend/tests/compose.r05.yaml in a fresh goat-r05-* project.
"""
import argparse
import hashlib
import json
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8086')
    parser.add_argument('--project', default='goat-r05-check')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--output', type=Path, default=Path('artifacts/r05'))
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {'localhost', '127.0.0.1', '::1'} or not args.project.startswith('goat-r05-'):
        parser.error('Use an isolated local goat-r05-* stack')
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    checks, errors = [], []
    digest = hashlib.sha256()
    for path in sorted((root / 'frontend/src').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    report = {'kind': 'R05 real browser/HTTP/PostgreSQL/worker with synthetic fixtures and synthetic AI',
              'paid_model_calls': 0, 'frontend_source_sha256': digest.hexdigest(), 'checks': checks, 'result': 'RUNNING'}

    def fixture(action):
        result = subprocess.run(['docker', 'compose', '-p', args.project, '-f', 'compose.yaml', '-f', 'frontend/tests/compose.r05.yaml',
                                 'exec', '-T', 'api', 'python', '/srv/r05/insight_fixture.py', action], cwd=root,
                                input=json.dumps({'password': password}) if action == 'seed' else '', capture_output=True, text=True, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Fixture failed: ' + result.stderr)

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS ' + name, flush=True)

    fixture('seed')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        try:
            page.goto(args.base_url + '/app/analytics')
            page.get_by_label('Email', exact=True).fill('r05-insight@example.org')
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Войти', exact=True).click()
            panel = page.get_by_role('region', name='Анализ события', exact=True)
            expect(page.get_by_role('button', name='Учебная карточка: исторический банк', exact=True)).to_be_visible()
            expect(panel.get_by_role('note')).to_contain_text('не являются официальной позицией банка')
            passed('real login and feed keep notice_v1 visible before preparation')

            def prepare(title):
                page.get_by_role('button', name=title, exact=True).click()
                with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/companies/r05-company-a/insights')) as request:
                    panel.get_by_role('button', name='Подготовить анализ', exact=True).click()
                return request.value

            response = prepare('Учебная карточка: исторический банк')
            assert response.status == 200
            expect(panel.get_by_text('Исторический банковский материал — не текущая позиция банка', exact=True)).to_be_visible()
            expect(panel.locator('time[datetime="2024-06-01"]')).to_be_visible()
            passed('saved v2 card comes from the real API with historical bank status and document date')
            bank = panel.get_by_role('region', name='Банковский материал', exact=True)
            bank.get_by_role('button', name='Основание 1', exact=True).click()
            pdf = bank.get_by_role('link', name='Открыть защищённый PDF · страница 3 ↗', exact=True)
            expect(pdf).to_have_attribute('href', '/api/sources/r05-historical-bank-2024/file#page=3')
            response = context.request.get(args.base_url + '/api/sources/r05-historical-bank-2024/file')
            assert response.status == 200 and response.body().startswith(b'%PDF')
            anonymous = browser.new_context()
            assert anonymous.request.get(args.base_url + '/api/sources/r05-historical-bank-2024/file').status == 401
            anonymous.close()
            passed('authorized PDF is readable at page 3; anonymous access is rejected')

            claim = panel.get_by_role('region', name='Что это значит для компании', exact=True)
            claim.get_by_role('button', name='Основание 1', exact=True).click()
            expect(claim.get_by_role('link', name='Первоисточник · example.org ↗', exact=True)).to_have_attribute('href', 'https://example.org/synthetic/historical')
            claim.get_by_role('button', name='Основание 2', exact=True).click()
            expect(claim.get_by_text('features.confirmed_floating_debt', exact=True)).to_be_visible()
            expect(claim.get_by_text('Значение: 1000000 RUB; плавающая ставка; пересмотр 01.11.2026', exact=True)).to_be_visible()
            assert context.request.get(args.base_url + '/api/sources/r05-foreign-source').status == 403
            page.screenshot(path=str(args.output / 'historical-desktop.png'), full_page=True)
            passed('claim references resolve to exact news URL/profile field; foreign company evidence is denied')

            assert prepare('Учебная карточка: без позиции банка').status == 200
            expect(panel.get_by_text('Позиция банка отсутствует', exact=True)).to_be_visible()
            expect(panel.get_by_role('region', name='Интерпретация ИИ', exact=True)).to_be_visible()
            passed('missing bank position does not block the external interpretation')

            assert prepare('Учебная карточка: старая версия v1').status == 200
            expect(panel.get_by_text('Карточка v1. Оценка влияния, актуальность и типы выводов не определены.', exact=True)).to_be_visible()
            expect(panel.get_by_role('note')).to_contain_text('не является индивидуальной инвестиционной рекомендацией')
            passed('legacy v1 preserves separate claims and the application-owned disclaimer')

            response = prepare('Учебная карточка: фоновое задание')
            assert response.status == 202
            job_id = response.json()['id']
            expect(panel.get_by_text('Synthetic test summary', exact=True)).to_be_visible(timeout=30_000)
            job = context.request.get(args.base_url + '/api/jobs/' + job_id).json()
            assert job['status'] == 'done' and job['result']['insight_id']
            report['worker_job_id'] = job_id
            report['worker_insight_id'] = job['result']['insight_id']
            passed('POST 202 → existing worker → done job → persisted v2 card through real HTTP polling')

            page.set_viewport_size({'width': 390, 'height': 844})
            expect(panel.get_by_role('note')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(args.output / 'insight-mobile.png'), full_page=True)
            passed('390px card has no horizontal overflow and keeps the disclaimer')
            fixture('stale')
            panel.get_by_role('button', name='Проверить актуальность', exact=True).click()
            expect(panel.get_by_text('Карточка устарела: входные данные изменились. Обновите анализ перед использованием.', exact=True)).to_be_visible()
            passed('server-side profile version change marks the displayed result stale')
            assert not errors
            report['result'] = 'PASS'
        except Exception:
            report['result'] = 'FAIL'
            page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            (args.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()

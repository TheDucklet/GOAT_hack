"""R09 real Chromium/HTTP/PostgreSQL/worker acceptance; no gateway or HTTP interception."""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8090')
    parser.add_argument('--channel', default='msedge')
    parser.add_argument('--output', type=Path, default=Path('artifacts/r09-browser'))
    args = parser.parse_args()
    if not args.project.startswith('goat-r09-') or urlsplit(args.base_url).hostname not in {'127.0.0.1', 'localhost'}:
        parser.error('Use a dedicated local goat-r09-* stack')
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    checks, errors = [], []
    report = {'kind': 'R09 real HTTP/PostgreSQL/worker; synthetic AI; no request interception', 'paid_calls': 0, 'result': 'RUNNING', 'checks': checks}
    digest = hashlib.sha256()
    for path in sorted((root / 'frontend/src').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    report['frontend_source_sha256'] = digest.hexdigest()

    def fixture(action):
        value = subprocess.run(['docker', '--context', 'desktop-linux', 'compose', '-p', args.project, '-f', 'compose.yaml', '-f', 'frontend/tests/compose.r09.yaml',
                                'exec', '-T', 'api', 'python', '/srv/r05/action_fixture.py', action], cwd=root,
                               env={**os.environ, 'AI_ENV_FILE': '.env.ai.example', 'IMAGE_TAG': 'r09-check'},
                               input=json.dumps({'password': password}) if action == 'seed' else '', text=True, encoding='utf-8', capture_output=True)
        if value.returncode:
            raise RuntimeError('Fixture failed: ' + value.stderr)
        return value.stdout

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS ' + name, flush=True)

    notice = 'Демонстрация — запрос в банк не отправлен'
    title = 'Учебная карточка: исторический банк'
    fixture('seed')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def login(target, email='r05-insight@example.org'):
            target.goto(args.base_url + '/app/analytics')
            target.get_by_label('Email', exact=True).fill(email)
            target.get_by_label('Пароль', exact=True).fill(password)
            target.get_by_role('button', name='Войти', exact=True).click()
            expect(target.get_by_role('button', name=title, exact=True)).to_be_visible()

        def select():
            page.get_by_role('button', name=title, exact=True).click()
            page.get_by_role('button', name='Подготовить анализ', exact=True).click()
            expect(page.get_by_role('button', name='Полезно', exact=True)).to_be_enabled(timeout=30_000)

        def demo():
            expect(page.get_by_text(notice, exact=True)).to_be_visible()
            page.get_by_role('button', name='Обсудить с менеджером', exact=True).click()
            expect(page.get_by_role('dialog')).to_contain_text(notice)
            page.get_by_role('button', name='Подтвердить изменение', exact=True).click()
            expect(page.get_by_text('Демо-обращение сохранено. ' + notice, exact=True)).to_be_visible()

        try:
            login(page); select()
            page.get_by_role('button', name='Полезно', exact=True).dblclick()
            expect(page.get_by_role('button', name='Полезно', exact=True)).to_have_attribute('aria-pressed', 'true')
            page.locator('.insight-actions').scroll_into_view_if_needed(); page.wait_for_timeout(1200)
            demo()
            counts = json.loads(fixture('counts'))
            assert counts['feedback'] == 1 and counts['demo'] == 1
            passed('feedback and confirmed demo saved in PostgreSQL; repeated clicks create one row')
            page.reload(); select()
            expect(page.get_by_role('button', name='Полезно', exact=True)).to_have_attribute('aria-pressed', 'true')
            demo()
            assert json.loads(fixture('counts'))['demo'] == 1
            passed('saved feedback restored and stable demo key deduplicated after reload')
            page.get_by_role('button', name='Скрыть', exact=True).click()
            expect(page.get_by_role('button', name=title, exact=True)).to_have_count(0)
            page.reload()
            expect(page.get_by_text('Скрытые события (1)', exact=True)).to_be_visible()
            page.get_by_text('Скрытые события (1)', exact=True).click()
            expect(page.locator('.hidden-events')).to_contain_text(title)
            other = browser.new_context(viewport={'width': 390, 'height': 844})
            other_page = other.new_page(); login(other_page, 'r09-other@example.org')
            expect(other_page.get_by_role('button', name=title, exact=True)).to_be_visible()
            passed('personal hide persists after reload; a second decision maker still sees the event')
            page.get_by_role('button', name='Вернуть', exact=True).click()
            expect(page.get_by_role('button', name=title, exact=True)).to_be_visible()
            assert json.loads(fixture('counts'))['dismissals'] == 0
            passed('restore from server history returns the event without affecting global visibility')
            page.set_viewport_size({'width': 390, 'height': 844}); select()
            expect(page.locator('.insight-panel')).to_contain_text('<script>window.__r09Xss=true</script>')
            assert page.evaluate('window.__r09Xss === undefined')
            bank = page.locator('.insight-panel').get_by_role('region', name='Банковский материал', exact=True)
            bank.get_by_role('button', name='Основание 1', exact=True).click()
            link = bank.get_by_role('link', name='Открыть защищённый PDF · страница 3 ↗', exact=True)
            expect(link).to_be_visible()
            source = context.request.get(args.base_url + link.get_attribute('href').split('#')[0])
            assert source.status == 200 and source.body().startswith(b'%PDF')
            page.locator('.insight-actions').scroll_into_view_if_needed()
            page.screenshot(path=str(args.output / 'mobile-actions.png'), full_page=True)
            expect(page.locator('.insight-panel [role="note"]')).to_be_visible()
            chat = page.get_by_role('region', name='Диалог по событию', exact=True)
            question = '<script>window.__r09ChatXss=true</script>'
            chat.get_by_role('textbox', name='Вопрос по событию', exact=True).fill(question)
            chat.get_by_role('button', name='Отправить вопрос', exact=True).click()
            expect(chat.get_by_text('Учебный условный ответ: ' + question, exact=True)).to_be_visible(timeout=30_000)
            assert page.evaluate('window.__r09ChatXss === undefined')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(args.output / 'mobile-chat.png'), full_page=True)
            passed('390px: authenticated source, saved card, feedback, chat worker response, notices and escaped script without horizontal overflow')
            metrics = json.loads(fixture('counts'))['product_events']
            assert {'open', 'impression', 'feedback', 'action', 'hide', 'restore', 'chat'} <= {row['kind'] for row in metrics}
            assert all(row['excluded_reason'] in {'bot', 'test'} for row in metrics)
            passed('content-free interaction events saved; headless test traffic excluded from product metrics')
            assert not errors, errors
            report['server_counts'] = json.loads(fixture('counts'))
            report['result'] = 'PASS'
            other.close()
        finally:
            report['page_errors'] = errors
            if report['result'] != 'PASS':
                report['result'] = 'FAIL'
                page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()

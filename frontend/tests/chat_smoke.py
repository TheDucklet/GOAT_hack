"""R06 real browser/API/PostgreSQL/worker acceptance with explicit synthetic AI.

No request interception. The script changes only its isolated goat_r06 database.
"""
import argparse
import hashlib
import json
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='goat-r06-check')
    parser.add_argument('--base-url', default='http://127.0.0.1:8087')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--output', type=Path, default=Path('artifacts/r06-browser'))
    args = parser.parse_args()
    if not args.project.startswith('goat-r06-') or urlsplit(args.base_url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('Use an isolated local goat-r06-* stack')
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    checks, errors, posts = [], [], []
    digest = hashlib.sha256()
    for path in sorted((root / 'frontend/src').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    report = {'kind': 'R06 real HTTP/PG/worker with synthetic AI; no HTTP interception', 'paid_calls': 0,
              'frontend_source_sha256': digest.hexdigest(), 'checks': checks, 'result': 'RUNNING'}

    def compose(*command, data=''):
        value = subprocess.run(['docker', 'compose', '-p', args.project, '-f', 'compose.yaml', '-f', 'frontend/tests/compose.r05.yaml',
                                '-f', 'frontend/tests/compose.r06.yaml', *command], cwd=root, input=data, text=True, encoding='utf-8', capture_output=True)
        if value.returncode:
            raise RuntimeError(f'Compose {command[0]} failed: ' + value.stderr)
        return value.stdout

    def fixture(action):
        return compose('exec', '-T', 'api', 'python', '/srv/r05/chat_fixture.py', action,
                       data=json.dumps({'password': password}) if action == 'seed' else '')

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS ' + name, flush=True)

    fixture('seed')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.on('request', lambda request: posts.append(request.post_data_json) if request.method == 'POST' and '/messages' in request.url else None)

        def panel():
            return page.get_by_role('region', name='Диалог по событию', exact=True)

        def login():
            page.get_by_label('Email', exact=True).fill('r05-insight@example.org')
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Войти', exact=True).click()

        def send(question):
            panel().get_by_role('textbox', name='Вопрос по событию', exact=True).fill(question)
            panel().get_by_role('button', name='Отправить вопрос', exact=True).click()

        def answered(question):
            expect(panel().get_by_text('Учебный условный ответ: ' + question, exact=True)).to_be_visible(timeout=30_000)
            expect(panel().get_by_role('textbox', name='Вопрос по событию')).to_have_value('')

        try:
            page.goto(args.base_url + '/app/analytics')
            login()
            page.get_by_role('button', name='Учебная карточка: исторический банк', exact=True).click()
            panel().get_by_role('button', name='Почему это важно нам?', exact=True).click()
            expect(panel().get_by_role('textbox', name='Вопрос по событию')).to_have_value('Почему это важно нам?')
            assert len(posts) == 0
            panel().get_by_role('button', name='Отправить вопрос', exact=True).click()
            answered('Почему это важно нам?')
            chat_a = panel().get_attribute('data-chat-id')
            assert chat_a and 'chat_id=' + chat_a in page.url
            send('Каких данных не хватает?'); answered('Каких данных не хватает?')
            assert len(posts) == 2
            expect(panel().get_by_role('list', name='История диалога').locator(':scope > li')).to_have_count(4)
            passed('two contextual questions pass POST → job polling → worker → saved assistant history without duplicate sends')

            page.reload()
            expect(panel().get_by_role('list', name='История диалога').locator(':scope > li')).to_have_count(4)
            expect(panel()).to_have_attribute('data-chat-id', chat_a)
            assert len(posts) == 2
            passed('reload restores server chat_id, event and four history messages without a new POST')
            first = panel().locator('.chat-assistant').first
            expect(panel().get_by_role('note')).to_contain_text('не являются официальной позицией банка')
            first.get_by_role('button', name='Основание 1', exact=True).click()
            expect(first.get_by_text('Исторический материал — не текущая позиция банка · проверено', exact=False)).to_be_visible()
            expect(first.get_by_text('Дата документа: 2024-06-01. Страница 3.', exact=True)).to_be_visible()
            expect(first.get_by_role('link', name='Открыть защищённый PDF · страница 3 ↗', exact=True)).to_have_attribute('href', '/api/sources/r05-historical-bank-2024/file#page=3')
            page.screenshot(path=str(args.output / 'chat-desktop.png'), full_page=True)
            passed('answer keeps notice, unknowns and authorized historical bank evidence with date/status/page')

            send('Учебный бюджетный отказ')
            expect(panel().get_by_text('Дневной бюджет ИИ исчерпан. Вопрос сохранён; повторите обработку после восстановления бюджета.', exact=True)).to_be_visible(timeout=30_000)
            expect(panel().get_by_role('textbox', name='Вопрос по событию')).to_have_value('Учебный бюджетный отказ')
            key = posts[-1]['client_message_id']
            panel().get_by_role('button', name='Повторить', exact=True).click()
            answered('Учебный бюджетный отказ')
            assert posts[-1]['client_message_id'] == key and posts[-1]['retry'] is True
            rows = context.request.get(args.base_url + f'/api/chats/{chat_a}/messages').json()
            assert sum(row['role'] == 'user' for row in rows) == 3 and len(rows) == 6
            passed('budget failure preserves the question; explicit retry reuses its key and creates no duplicate user message')

            compose('stop', 'api')
            send('Вопрос после сетевого отказа')
            expect(panel().get_by_role('alert')).to_be_visible(timeout=25_000)
            expect(panel().get_by_role('textbox', name='Вопрос по событию')).to_have_value('Вопрос после сетевого отказа')
            compose('start', 'api')
            for _ in range(30):
                if context.request.get(args.base_url + '/health').status == 200:
                    break
                time.sleep(1)
            panel().get_by_role('button', name='Повторить', exact=True).click()
            answered('Вопрос после сетевого отказа')
            passed('real API outage preserves the draft and recovers only after a manual retry')

            fixture('expire-session')
            send('Сохранить при повторном входе')
            expect(page).to_have_url(args.base_url + '/login')
            sent_before_login = len(posts)
            login()
            expect(panel().get_by_role('textbox', name='Вопрос по событию')).to_have_value('Сохранить при повторном входе')
            assert len(posts) == sent_before_login
            panel().get_by_role('button', name='Отправить вопрос', exact=True).click()
            answered('Сохранить при повторном входе')
            passed('401 redirects to login and restores the same draft without automatically resending it')

            page.get_by_role('combobox', name='Компания', exact=True).select_option('r05-company-b')
            expect(page.locator('.chat-panel[data-chat-id]')).to_have_count(0)
            expect(page.get_by_text('Учебный условный ответ: Почему это важно нам?', exact=True)).to_have_count(0)
            page.get_by_role('button', name='Учебная карточка: исторический банк', exact=True).click()
            send('Отдельный вопрос компании B'); answered('Отдельный вопрос компании B')
            chat_b = panel().get_attribute('data-chat-id')
            assert chat_b != chat_a
            page.reload()
            expect(page.get_by_role('combobox', name='Компания')).to_have_value('r05-company-b')
            expect(panel()).to_have_attribute('data-chat-id', chat_b)
            expect(panel().get_by_text('Учебный условный ответ: Отдельный вопрос компании B', exact=True)).to_be_visible()
            passed('company switch clears the prior chat; a company B conversation restores its own context after reload')

            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            expect(panel().get_by_role('note')).to_be_visible()
            page.screenshot(path=str(args.output / 'chat-mobile.png'), full_page=True)
            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            passed('390px chat has no overflow and stores no question or session secrets in browser storage')
            counts = json.loads(fixture('counts'))
            assert counts == {'user': 6, 'assistant': 6}, counts
            assert not errors
            report.update(result='PASS', counts=counts, chat_ids=[chat_a, chat_b])
        except Exception:
            report['result'] = 'FAIL'
            page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            compose('start', 'api')
            (args.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()

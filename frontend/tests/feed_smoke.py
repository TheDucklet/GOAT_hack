"""R-04 real browser/API/PostgreSQL acceptance on a dedicated local Compose stack.

Requires playwright==1.58.0 and an empty database (no seed-demo). Does not intercept
HTTP requests. Creates 25 synthetic events, two companies and one ordinary user.
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
    parser.add_argument('--base-url', default='http://127.0.0.1:8084')
    parser.add_argument('--project', default='goat-r04-check')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--output', type=Path, default=Path('artifacts/r04'))
    options = parser.parse_args()
    base = options.base_url.rstrip('/')
    if urlsplit(base).hostname not in {'localhost', '127.0.0.1', '::1'} or not options.project.startswith('goat-r04-'):
        parser.error('Use a dedicated local goat-r04-* acceptance stack.')
    options.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    fixture_code = Path(__file__).with_name('feed_fixture.py').read_text(encoding='utf-8')

    def fixture(action):
        result = subprocess.run(['docker', 'compose', '-p', options.project, 'exec', '-T', 'api',
                                 'python', '-c', fixture_code, action],
                                input=json.dumps({'password': password}) if action == 'seed' else '',
                                text=True, capture_output=True, encoding='utf-8', check=False)
        if result.returncode:
            raise RuntimeError(f'Fixture {action} failed: {result.stderr}')

    checks, errors = [], []
    source_root = Path(__file__).resolve().parents[1] / 'src'
    source_hash = hashlib.sha256()
    for path in sorted(source_root.rglob('*')):
        if path.is_file():
            source_hash.update(path.relative_to(source_root).as_posix().encode() + b'\0' + path.read_bytes())
    report = {'kind': 'R-04 real browser/API/PostgreSQL acceptance', 'base_url': base,
              'frontend_source_sha256': source_hash.hexdigest(), 'checks': checks}

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS', name, flush=True)

    fixture('seed')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=options.channel)
        context = browser.new_context(viewport={'width': 1600, 'height': 1100})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(type(error).__name__))
        try:
            page.goto(base + '/app/analytics')
            expect(page).to_have_url(base + '/login')
            passed('anonymous analytics URL redirects to login')
            page.get_by_label('Email', exact=True).fill('r04-feed@example.org')
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Войти', exact=True).click()
            expect(page.get_by_role('heading', name='Персональная лента', exact=True)).to_be_visible()
            expect(page.locator('.feed-event')).to_have_count(20)
            passed('HTTP login opens the real feed with the first 20 events')
            response = context.request.get(base + '/api/companies/r04-acceptance-a/feed?limit=20&offset=0')
            assert response.status == 200
            first = response.json()
            assert first['total'] == 25
            titles = page.locator('.event-select').all_text_contents()
            assert titles == [item['title'] for item in first['items']]
            expect(page.locator('.feed-event').first.locator('.event-summary')).to_have_text(first['items'][0]['summary'])
            assert page.locator('.feed-event').first.locator('time').get_attribute('datetime') == first['items'][0]['published_at']
            expect(page.locator('.feed-event').first.get_by_role('link', name='example.org ↗')).to_have_attribute('href', first['items'][0]['sources'][0]['url'])
            expect(page.get_by_text('Отрасль: 25.61', exact=True).first).to_be_visible()
            passed('title, summary, date, source URL and relevance reasons match the live API')
            page.get_by_role('button', name='Загрузить ещё', exact=True).click()
            expect(page.locator('.feed-event')).to_have_count(25)
            expect(page.get_by_role('button', name='Загрузить ещё', exact=True)).to_have_count(0)
            assert len(set(page.locator('.event-select').all_text_contents())) == 25
            passed('next page appends the remaining five events without duplicates')
            page.get_by_role('button', name='Тестовое событие 00', exact=True).click()
            for name in ['Анализ события', 'Диалог по событию']:
                expect(page.get_by_role('region', name=name, exact=True)).to_have_attribute('data-event-id', 'r04-acceptance-00')
            passed('insight and chat panels receive the same selected event id')
            page.screenshot(path=str(options.output / 'feed-desktop.png'))
            page.get_by_role('combobox', name='Компания', exact=True).select_option('r04-acceptance-b')
            expect(page.locator('.feed-event')).to_have_count(20)
            expect(page.get_by_role('region', name='Анализ события', exact=True)).not_to_have_attribute('data-event-id', 'r04-acceptance-00')
            expect(page.locator('[aria-pressed="true"]')).to_have_count(0)
            second = context.request.get(base + '/api/companies/r04-acceptance-b/feed?limit=20&offset=0').json()
            assert page.locator('.event-select').all_text_contents() == [item['title'] for item in second['items']]
            assert second['items'][0]['event_id'] != first['items'][0]['event_id']
            passed('company switch clears selection/pages and loads its personalized server ranking')
            page.get_by_role('combobox', name='Компания', exact=True).select_option('r04-acceptance-a')
            expect(page.get_by_role('button', name='Тестовое событие 00', exact=True)).to_be_visible()
            fixture('update')
            page.get_by_role('button', name='Обновить ленту', exact=True).click()
            expect(page.get_by_role('button', name='Новость обновлена в backend', exact=True)).to_be_visible()
            expect(page.get_by_text('Изменение из PostgreSQL видно в интерфейсе.', exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_role('button', name='Новость обновлена в backend', exact=True)).to_be_visible()
            passed('changing a real PostgreSQL event appears after feed refresh and full browser reload')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.get_by_role('button', name='Новость обновлена в backend', exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.screenshot(path=str(options.output / 'feed-mobile.png'))
            passed('390px mobile feed has selectable events and no horizontal overflow')
            fixture('hide')
            page.get_by_role('button', name='Обновить ленту', exact=True).click()
            expect(page.get_by_text('Нет подходящих событий', exact=True)).to_be_visible()
            expect(page.locator('.feed-event')).to_have_count(0)
            page.screenshot(path=str(options.output / 'feed-empty.png'), full_page=True)
            passed('a real empty API response displays the required empty state')
            fixture('show')
            page.get_by_role('button', name='Обновить ленту', exact=True).click()
            expect(page.locator('.feed-event')).to_have_count(20)
            page.goto(base + '/app')
            expect(page.get_by_role('link', name='Открыть бизнес-аналитику', exact=False)).to_be_visible()
            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            passed('the main screen retains its analytics entry and stores no session secrets')
            assert not errors
            passed('browser reports no uncaught JavaScript errors')
            report['result'] = 'PASS'
        except Exception as error:
            report['result'] = 'FAIL'
            report['error_type'] = type(error).__name__
            raise
        finally:
            fixture('show')
            (options.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
    print(f'Result: PASS; {len(checks)} checks')


if __name__ == '__main__':
    main()

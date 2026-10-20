"""Production preview + actual browser fetch, with intercepted A-01 responses.

Start npm run preview after an HTTP build. This is a transport harness, not a live backend.
python tests/http_smoke.py --channel msedge
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:4173')
    parser.add_argument('--channel', default=None)
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    examples = json.loads((root / 'docs/contracts/examples.json').read_text(encoding='utf-8'))
    me = next(item['data'] for item in examples if item['name'] == 'me')
    company = {'id': me['memberships'][0]['company_id'], 'name': 'Компания A', 'profile_version': 'demo-v1'}
    state = {'logged_in': False, 'unavailable': False}
    requests = []

    def api_route(route):
        request = route.request
        path = request.url.split('/api', 1)[1]
        headers = request.all_headers()
        requests.append({'path': path, 'method': request.method, 'cookie_sent': 'goat_session=synthetic' in headers.get('cookie', ''), 'csrf_matches': headers.get('x-csrf-token') == me['csrf_token']})
        status, data, response_headers = 200, {}, {}
        if path == '/auth/login':
            assert json.loads(request.post_data)['email'] == me['email']
            assert 'x-csrf-token' not in headers
            state['logged_in'] = True
            data = me
            response_headers['Set-Cookie'] = 'goat_session=synthetic; Path=/; HttpOnly; SameSite=Lax'
        elif state['unavailable']:
            status, data = 503, {'code': 'unavailable', 'message': 'Сервис недоступен', 'request_id': 'http-test', 'field_errors': []}
        elif not state['logged_in']:
            status, data = 401, {'code': 'unauthenticated', 'message': 'Войдите', 'request_id': 'http-test', 'field_errors': []}
        else:
            assert 'goat_session=synthetic' in headers.get('cookie', '')
            if path == '/me':
                data = me
            elif path == '/companies':
                data = [company]
            elif path == '/admin/stats':
                status, data = 403, {'code': 'forbidden', 'message': 'Нет доступа', 'request_id': 'http-test', 'field_errors': []}
            elif path == '/auth/logout':
                assert headers.get('x-csrf-token') == me['csrf_token']
                state['logged_in'] = False
                status, data = 204, None
                response_headers['Set-Cookie'] = 'goat_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax'
            else:
                raise AssertionError(f'Unexpected request: {path}')
        route.fulfill(status=status, content_type='application/json', headers=response_headers, body='' if data is None else json.dumps(data))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=options.channel)
        context = browser.new_context()
        context.route('**/api/**', api_route)
        page = context.new_page()
        page.goto(options.base_url + '/app')
        expect(page).to_have_url(options.base_url + '/login')
        expect(page.get_by_text('Демонстрационный вход', exact=True)).to_have_count(0)
        page.get_by_label('Email', exact=True).fill(me['email'])
        page.get_by_label('Пароль', exact=True).fill('synthetic-http-test')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page.locator('#company')).to_have_value(company['id'])
        cookie = next(item for item in context.cookies() if item['name'] == 'goat_session')
        assert cookie['httpOnly'] is True
        assert page.evaluate('document.cookie').find('goat_session') == -1
        for route, title in [('/app', 'Ваш бизнес в фокусе'), ('/app/analytics', 'Бизнес-аналитика'), ('/admin', 'Администрирование')]:
            response = page.goto(options.base_url + route)
            assert response.status == 200
            expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
        expect(page.get_by_role('alert')).to_contain_text('Нет доступа')
        page.get_by_role('button', name='Выйти', exact=True).click()
        expect(page).to_have_url(options.base_url + '/login')
        state['unavailable'] = True
        page.goto(options.base_url + '/app')
        expect(page.get_by_role('alert')).to_contain_text('Сервис временно недоступен')
        expect(page).to_have_url(options.base_url + '/app')
        state['unavailable'] = False
        page.get_by_role('button', name='Повторить').click()
        expect(page).to_have_url(options.base_url + '/login')
        report = {'date': '2026-10-20', 'kind': 'production HTTP browser interception harness; not live backend', 'result': 'PASS', 'http_only_cookie': True, 'csrf_on_logout': True, 'no_mock_fallback': True, 'requests': requests}
        (root / 'docs/qa/r-01-http.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        browser.close()


if __name__ == '__main__':
    main()

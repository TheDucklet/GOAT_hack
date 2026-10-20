"""R-01 browser acceptance. Start Vite with VITE_API_MODE=mock first.

python tests/browser_smoke.py --channel msedge
Requires playwright==1.58.0 and Edge, or an installed Playwright Chromium.
"""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--base-url', default='http://127.0.0.1:5173')
    args.add_argument('--channel', default=None)
    options = args.parse_args()
    output = Path(__file__).resolve().parents[2] / 'docs' / 'qa'
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=options.channel)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        for route in ['/login', '/register', '/app', '/app/analytics', '/admin']:
            response = page.goto(options.base_url + route)
            assert response.status == 200, (route, response.status)
            if route.startswith('/app') or route == '/admin':
                expect(page).to_have_url(options.base_url + '/login')
            checks.append(f'PASS direct URL {route}')

        page.goto(options.base_url + '/register')
        page.get_by_role('button', name='Зарегистрироваться', exact=True).click()
        expect(page.locator('#email-error')).to_have_text('Введите корректный email.')
        expect(page.locator('#password-error')).to_have_text('Пароль должен содержать от 10 до 256 символов.')
        checks.append('PASS 422 shown beside email/password')

        page.goto(options.base_url + '/login')
        page.get_by_label('Email', exact=True).fill('unavailable@example.org')
        page.get_by_label('Пароль', exact=True).fill('Demo-password-2026')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('Сервис временно недоступен')
        expect(page.get_by_label('Email', exact=True)).to_have_value('unavailable@example.org')
        checks.append('PASS 503 visible, form preserves input')

        page.get_by_label('Email', exact=True).fill('demo@example.org')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page).to_have_url(options.base_url + '/app')
        expect(page.locator('#company')).to_have_value('demo_company_a')
        expect(page.get_by_text('demo@example.org', exact=True)).to_be_visible()
        page.screenshot(path=str(output / 'r-01-desktop.png'), full_page=True)
        checks.append('PASS login, shared company/user header')

        for route, title in [('/app', 'Ваш бизнес в фокусе'), ('/app/analytics', 'Бизнес-аналитика')]:
            response = page.goto(options.base_url + route)
            assert response.status == 200
            expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_role('heading', name=title, exact=True)).to_be_visible()
            checks.append(f'PASS authenticated direct URL/reload {route}')

        page.goto(options.base_url + '/admin')
        expect(page.get_by_role('alert')).to_contain_text('Нет доступа')
        checks.append('PASS ordinary user receives visible 403 on /admin')

        page.goto(options.base_url + '/app/analytics')
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.get_by_role('heading', name='Бизнес-аналитика', exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(output / 'r-01-mobile.png'), full_page=True)
        checks.append('PASS 390px, no horizontal overflow')

        page.get_by_role('button', name='Выйти', exact=True).click()
        expect(page).to_have_url(options.base_url + '/login')
        expect(page.get_by_role('heading', name='С возвращением')).to_be_visible()
        checks.append('PASS logout and session reset')

        page.goto(options.base_url + '/login')
        page.get_by_label('Email', exact=True).fill('admin@example.org')
        page.get_by_label('Пароль', exact=True).fill('Demo-password-2026')
        page.get_by_role('button', name='Войти', exact=True).click()
        expect(page).to_have_url(options.base_url + '/app/analytics')
        page.goto(options.base_url + '/admin')
        expect(page.get_by_text('Оценок полезности', exact=True)).to_be_visible()
        checks.append('PASS administrator can open /admin')

        assert not errors, errors
        report = {'date': '2026-10-20', 'browser': browser.version, 'api': 'A-01 examples.json at 7f86298; local mock transport', 'checks': checks, 'page_errors': errors}
        (output / 'r-01-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        context.close()
        browser.close()


if __name__ == '__main__':
    main()

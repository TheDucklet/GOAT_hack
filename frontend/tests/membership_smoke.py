"""R-03 acceptance against the local, real Compose stack (no intercepted requests).

Requires playwright==1.58.0 and seed-demo. Creates one synthetic user/membership;
the seeded administrator approves/rejects only that new membership. Existing
users and memberships are not modified. Passwords/tokens stay in memory.
"""
import argparse
import json
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--company-id', default='demo_company_a')
    parser.add_argument('--output', type=Path, default=Path('artifacts/r03'))
    options = parser.parse_args()
    base = options.base_url.rstrip('/')
    if urlsplit(base).hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('This synthetic acceptance script only supports a local stack.')
    options.output.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    payload_keys = []
    report = {'kind': 'R-03 real browser and API acceptance', 'base_url': base, 'checks': checks}

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS', name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=options.channel)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        administrator = browser.new_context()
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(type(error).__name__))

        def record_keys(request):
            if request.method in {'POST', 'PATCH'} and '/api/' in request.url and request.post_data:
                payload_keys.append(set(request.post_data_json))

        page.on('request', record_keys)
        email = f'r03-{uuid.uuid4().hex}@example.org'
        password = secrets.token_urlsafe(24)
        position = 'Руководитель нестандартного направления'
        long_position = position + ' / развитие новых международных направлений' * 16
        try:
            page.goto(base + '/app/companies')
            expect(page).to_have_url(base + '/login')
            passed('anonymous membership URL redirects to login')

            page.goto(base + '/register')
            page.get_by_role('button', name='Зарегистрироваться', exact=True).click()
            expect(page.get_by_label('Email', exact=True)).to_have_attribute('aria-invalid', 'true')
            expect(page.get_by_label('Пароль', exact=True)).to_have_attribute('aria-invalid', 'true')
            passed('server 422 registration errors appear beside email and password')
            page.get_by_label('Email', exact=True).fill(email)
            page.get_by_label('Пароль', exact=True).fill(password)
            with page.expect_response(lambda response: response.url.endswith('/api/auth/register') and response.request.method == 'POST') as registered:
                page.get_by_role('button', name='Зарегистрироваться', exact=True).click()
            assert registered.value.status == 201
            expect(page).to_have_url(base + '/login')
            assert not any(cookie['name'] == 'goat_session' for cookie in context.cookies())
            passed('UI registration creates a user without creating a client-side session')

            page.goto(base + '/register')
            page.get_by_label('Email', exact=True).fill(email)
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Зарегистрироваться', exact=True).click()
            expect(page.get_by_label('Email', exact=True)).to_have_attribute('aria-invalid', 'true')
            expect(page.locator('#email-error')).to_contain_text('Email уже зарегистрирован')
            passed('occupied email is reported beside the email field')

            page.goto(base + '/login')
            page.get_by_label('Email', exact=True).fill(email)
            page.get_by_label('Пароль', exact=True).fill('wrong-password-for-synthetic-user')
            page.get_by_role('button', name='Войти', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('Неверный email или пароль')
            expect(page).to_have_url(base + '/login')
            passed('unknown password produces visible 401 without a redirect loop')
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Войти', exact=True).click()
            expect(page).to_have_url(base + '/app')
            expect(page.locator('#company')).to_be_disabled()
            assert any(cookie['name'] == 'goat_session' and cookie['httpOnly'] for cookie in context.cookies())
            assert 'goat_session' not in page.evaluate('document.cookie')
            passed('UI login uses the server HttpOnly cookie and has no company access')

            page.goto(base + '/app/analytics')
            expect(page.get_by_role('heading', name='Нужен доступ к компании')).to_be_visible()
            assert context.request.get(base + f'/api/companies/{options.company_id}/feed').status == 403
            passed('new user cannot view company analytics or fetch its feed')
            page.goto(base + '/app/companies')
            form = page.get_by_role('form', name='Заявка на компанию')
            form.get_by_label('Идентификатор компании').fill('r03-company-does-not-exist')
            form.get_by_role('button', name='Отправить заявку').click()
            expect(form.get_by_label('Идентификатор компании')).to_have_attribute('aria-invalid', 'true')
            passed('unknown company produces a visible field error')
            form.get_by_label('Идентификатор компании').fill(options.company_id)
            form.get_by_label('Должность', exact=True).fill(position)
            form.get_by_label('Интересы', exact=True).fill('Налоги\nМеждународные расчёты')
            with page.expect_response(lambda response: response.url.endswith('/api/memberships/requests')) as requested:
                form.get_by_role('button', name='Отправить заявку').click()
            assert requested.value.status == 201
            membership = requested.value.json()
            assert membership['status'] == 'pending'
            expect(page.get_by_text('Ожидает подтверждения', exact=True)).to_be_visible()
            expect(page.locator('#company')).to_be_disabled()
            assert context.request.get(base + '/api/companies').json() == []
            passed('membership request remains pending and does not grant company access')

            form.get_by_label('Идентификатор компании').fill(options.company_id)
            form.get_by_role('button', name='Отправить заявку').click()
            expect(form.get_by_label('Идентификатор компании')).to_have_attribute('aria-invalid', 'true')
            expect(form.get_by_role('alert')).to_contain_text('Членство или заявка уже существует')
            passed('duplicate membership request produces visible server 409')
            page.reload()
            expect(page.get_by_text('Ожидает подтверждения', exact=True)).to_be_visible()
            profile = page.get_by_role('form', name=f'Профиль: {options.company_id}', exact=True)
            expect(profile.get_by_label('Должность', exact=True)).to_have_value(position)
            passed('pending membership and its profile survive page reload')

            profile.get_by_label('Должность', exact=True).fill('Д' * 1001)
            profile.get_by_role('button', name='Сохранить профиль').click()
            expect(profile.get_by_label('Должность', exact=True)).to_have_attribute('aria-invalid', 'true')
            passed('server rejects positions over 1000 characters beside the position field')
            profile.get_by_label('Должность', exact=True).fill(long_position)
            profile.get_by_role('button', name='Сохранить профиль').click()
            expect(profile.get_by_text('Профиль сохранён.', exact=True)).to_be_visible()
            page.reload()
            profile = page.get_by_role('form', name=f'Профиль: {options.company_id}', exact=True)
            expect(profile.get_by_label('Должность', exact=True)).to_have_value(long_position)
            expect(profile.get_by_label('Интересы', exact=True)).to_have_value('Налоги\nМеждународные расчёты')
            me = context.request.get(base + '/api/me').json()
            assert me['system_role'] == 'user' and me['memberships'][0]['status'] == 'pending'
            passed('arbitrary long position and interests persist without changing system_role=user')
            profile.get_by_label('Должность', exact=True).fill(position)
            profile.get_by_role('button', name='Сохранить профиль').click()
            expect(profile.get_by_text('Профиль сохранён.', exact=True)).to_be_visible()
            page.screenshot(path=str(options.output / 'pending-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            expect(page.get_by_role('heading', name='Компании и профиль', exact=True)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(options.output / 'pending-mobile.png'), full_page=True)
            passed('membership forms fit a 390px viewport without horizontal overflow')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(base + '/admin')
            expect(page.get_by_role('alert')).to_contain_text('Нет доступа')
            passed('direct admin URL remains forbidden to an ordinary user')

            admin_login = administrator.request.post(base + '/api/auth/login', data={
                'email': os.environ.get('R03_ADMIN_EMAIL', 'admin@goat.example.org'),
                'password': os.environ.get('R03_ADMIN_PASSWORD', 'Local-demo-password-2026'),
            }, headers={'Origin': base})
            assert admin_login.status == 200
            admin_headers = {'X-CSRF-Token': admin_login.json()['csrf_token']}
            endpoint = base + '/api/admin/memberships/' + membership['id']
            assert administrator.request.patch(endpoint, data={'status': 'active'}, headers=admin_headers).status == 200
            page.goto(base + '/app/companies')
            expect(page.get_by_text('Доступ открыт', exact=True)).to_be_visible()
            expect(page.locator('#company')).to_have_value(options.company_id)
            assert context.request.get(base + f'/api/companies/{options.company_id}/feed').status == 200
            passed('only server approval makes the company and its feed accessible')
            profile = page.get_by_role('form', name='Профиль:', exact=False)
            expect(profile.get_by_label('Должность', exact=True)).to_have_value(position)
            assert context.request.get(base + '/api/me').json()['system_role'] == 'user'
            page.screenshot(path=str(options.output / 'active-desktop.png'), full_page=True)
            passed('the requested nonstandard position persists after approval and reload')

            assert administrator.request.patch(endpoint, data={'status': 'rejected'}, headers=admin_headers).status == 200
            page.get_by_role('button', name='Обновить доступ', exact=True).click()
            expect(page.get_by_text('Заявка отклонена', exact=True)).to_be_visible()
            expect(page.locator('#company')).to_be_disabled()
            assert context.request.get(base + f'/api/companies/{options.company_id}/feed').status == 403
            passed('refresh reflects server rejection and removes company access')
            assert administrator.request.patch(endpoint, data={'status': 'active'}, headers=admin_headers).status == 200
            page.get_by_role('button', name='Обновить доступ', exact=True).click()
            expect(page.locator('#company')).to_have_value(options.company_id)
            passed('refresh detects subsequent approval without another login')

            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            assert payload_keys and all(keys <= {'email', 'password', 'company_id', 'position_text', 'interests'} for keys in payload_keys)
            passed('passwords/tokens are absent from browser storage and payloads never include roles or membership status')
            page.get_by_role('button', name='Выйти', exact=True).click()
            expect(page).to_have_url(base + '/login')
            assert context.request.get(base + '/api/me').status == 401
            assert administrator.request.post(base + '/api/auth/logout', headers=admin_headers).status == 204
            passed('UI logout revokes the server session')
            assert not errors
            passed('browser has no uncaught JavaScript errors')
            report['result'] = 'PASS'
        except Exception as error:
            report['result'] = 'FAIL'
            report['error_type'] = type(error).__name__
            raise
        finally:
            (options.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()
    print(f'Result: PASS; {len(checks)} checks; report: {options.output / "browser.json"}')


if __name__ == '__main__':
    main()

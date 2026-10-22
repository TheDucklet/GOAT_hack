"""R07 real browser/API/PostgreSQL acceptance; no intercepted HTTP or AI calls."""
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
    parser.add_argument('--project', default='goat-r07-check')
    parser.add_argument('--base-url', default='http://127.0.0.1:8088')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--output', type=Path, default=Path('artifacts/r07-browser'))
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if not args.project.startswith('goat-r07-') or urlsplit(base).hostname not in {'127.0.0.1', 'localhost', '::1'}:
        parser.error('Use an isolated local goat-r07-* stack')
    root = Path(__file__).resolve().parents[2]
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    seed = subprocess.run(['docker', 'compose', '-p', args.project, '-f', 'compose.yaml', '-f', 'frontend/tests/compose.r07.yaml',
                           'exec', '-T', 'api', 'python', '/srv/r07/access_fixture.py'], cwd=root,
                          input=json.dumps({'password': password}), text=True, encoding='utf-8', capture_output=True)
    if seed.returncode:
        raise RuntimeError(seed.stderr)
    checks, errors, mutations = [], [], []
    digest = hashlib.sha256()
    for path in sorted((root / 'frontend/src').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    report = {'kind': 'R07 real HTTP/PG/browser, isolated synthetic accounts, no HTTP interception',
              'frontend_source_sha256': digest.hexdigest(), 'checks': checks, 'result': 'RUNNING'}

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS ' + name, flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=args.channel)
        admin_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        director_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        finance_context = browser.new_context()
        operator = admin_context.new_page()
        director = director_context.new_page()
        finance = finance_context.new_page()
        for page in [operator, director, finance]:
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
        operator.on('request', lambda request: mutations.append(request.post_data_json) if request.method == 'PATCH' and '/api/admin/' in request.url else None)

        def login(page, email):
            page.get_by_label('Email', exact=True).fill(email)
            page.get_by_label('Пароль', exact=True).fill(password)
            page.get_by_role('button', name='Войти', exact=True).click()

        def membership(email, company):
            return operator.get_by_role('article', name=f'Заявка: {email}, {company}', exact=True)

        def confirm():
            dialog = operator.get_by_role('dialog')
            expect(dialog).to_be_visible()
            dialog.get_by_role('button', name='Подтвердить изменение', exact=True).click()
            expect(dialog).not_to_be_visible()

        try:
            director.goto(base + '/app/companies')
            login(director, 'user_b@goat.example.org')
            expect(director.get_by_text('Ожидает подтверждения', exact=True)).to_be_visible()
            assert director_context.request.get(base + '/api/companies/demo_company_a/feed').status == 403
            operator.goto(base + '/admin/memberships')
            login(operator, 'admin@goat.example.org')
            request = membership('user_b@goat.example.org', 'demo_company_a')
            expect(request).to_contain_text('Генеральный директор / международное развитие')
            request.get_by_role('button', name='Подтвердить доступ', exact=True).click()
            expect(operator.get_by_role('dialog')).to_contain_text('Компания: demo_company_a')
            operator.keyboard.press('Escape')
            expect(operator.get_by_role('dialog')).not_to_be_visible()
            assert not mutations
            request.get_by_role('button', name='Подтвердить доступ', exact=True).click()
            confirm()
            expect(request.get_by_text('Доступ открыт', exact=True)).to_be_visible()
            director.get_by_role('button', name='Обновить доступ', exact=True).click()
            expect(director.locator('#company option[value="demo_company_a"]')).to_have_count(1)
            assert director_context.request.get(base + '/api/companies/demo_company_a/feed').status == 200
            passed('confirmation/Escape perform no PATCH; explicit approval opens the company after /me refresh')

            request = membership('user_a@goat.example.org', 'demo_company_b')
            request.get_by_role('button', name='Подтвердить доступ', exact=True).click(); confirm()
            finance.goto(base + '/app/companies'); login(finance, 'user_a@goat.example.org')
            expect(finance.locator('#company option')).to_have_count(2)
            b_me = director_context.request.get(base + '/api/me').json()
            a_me = finance_context.request.get(base + '/api/me').json()
            assert {row['company_id'] for row in a_me['memberships'] if row['status'] == 'active'} == {'demo_company_a', 'demo_company_b'}
            assert any(row['company_id'] == 'demo_company_a' and row['status'] == 'active' for row in b_me['memberships'])
            assert a_me['system_role'] == b_me['system_role'] == 'user'
            passed('two decision makers share company A and one account has two companies without granting an admin role')

            request = membership('r07-request@example.org', 'demo_company_a')
            request.get_by_role('button', name='Отклонить заявку', exact=True).click(); confirm()
            expect(request.get_by_text('Заявка отклонена', exact=True)).to_be_visible()
            operator.reload()
            expect(membership('r07-request@example.org', 'demo_company_a')).to_contain_text('Заявка отклонена')
            operator.screenshot(path=str(args.output / 'memberships-desktop.png'), full_page=True)
            passed('rejection has a visible server result and survives a page reload')

            operator.get_by_role('link', name='Пользователи', exact=True).click()
            own = operator.get_by_role('article', name='Пользователь: admin@goat.example.org', exact=True)
            expect(own).to_contain_text('Собственный доступ отозвать нельзя')
            expect(own.get_by_role('button', name='Заблокировать', exact=True)).to_have_count(0)
            account = operator.get_by_role('article', name='Пользователь: user_b@goat.example.org', exact=True)
            account.get_by_role('button', name='Заблокировать', exact=True).click(); confirm()
            expect(account.get_by_text('Заблокирован', exact=True)).to_be_visible()
            assert director_context.request.get(base + '/api/me').status == 401
            director.get_by_role('button', name='Обновить доступ', exact=True).click()
            expect(director).to_have_url(base + '/login')
            passed('blocking through the UI revokes the existing session and redirects protected requests to login')

            account.get_by_role('button', name='Разблокировать', exact=True).click(); confirm()
            assert director_context.request.get(base + '/api/me').status == 401
            login(director, 'user_b@goat.example.org')
            expect(director.get_by_role('heading', name='Компании и профиль', exact=True)).to_be_visible()
            passed('unblocking requires a new login; the old session is never restored')

            for path in ['/admin', '/admin/users', '/admin/memberships', '/admin/users/memberships']:
                director.goto(base + path)
                expect(director.get_by_role('alert')).to_contain_text('Нет доступа')
                expect(director.locator('.access-card')).to_have_count(0)
            for path in ['/admin/users', '/admin/memberships']:
                assert director_context.request.get(base + '/api' + path).status == 403
            passed('an ordinary user sees a server-backed 403 on every direct admin URL and cannot read admin APIs')

            operator.set_viewport_size({'width': 390, 'height': 844})
            expect(account).to_be_visible()
            assert operator.evaluate('document.documentElement.scrollWidth <= innerWidth')
            account.get_by_role('button', name='Заблокировать', exact=True).click()
            expect(operator.get_by_role('dialog')).to_be_visible()
            assert operator.evaluate('document.documentElement.scrollWidth <= innerWidth')
            operator.screenshot(path=str(args.output / 'confirmation-mobile.png'), full_page=True)
            operator.get_by_role('button', name='Отмена', exact=True).click()
            assert operator.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            assert len(mutations) == 5 and all(set(body) == {'status'} for body in mutations)
            assert not errors
            passed('390px lists and native confirmation fit the viewport; only five explicit status-only PATCH requests were sent')
            report.update(result='PASS', explicit_mutations=len(mutations))
        except Exception:
            report['result'] = 'FAIL'
            operator.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            (args.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()

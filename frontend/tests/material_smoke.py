"""R08 real HTTP/PG/worker/OCR acceptance. Requires explicitly authorized gateway use.

Uploads the provided three-page Inflation_tracker_02.pdf. Synthetic fixtures only
prepare accounts, a visibility event and an intentionally missing file failure.
No HTTP interception, gateway stubs or model answers are used.
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
    parser.add_argument('--project', default='goat-r08-check')
    parser.add_argument('--base-url', default='http://127.0.0.1:8089')
    parser.add_argument('--channel', default=None)
    parser.add_argument('--output', type=Path, default=Path('artifacts/r08-browser'))
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    if not args.project.startswith('goat-r08-') or urlsplit(base).hostname not in {'localhost', '127.0.0.1', '::1'}:
        parser.error('Use an isolated local goat-r08-* stack')
    root = Path(__file__).resolve().parents[2]
    pdf = root.parent / 'data2/Inflation_tracker_02.pdf'
    args.output.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(24)
    checks, errors, mutations = [], [], []
    digest = hashlib.sha256()
    for path in sorted((root / 'frontend/src').rglob('*')):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode() + b'\0' + path.read_bytes())
    report = {'kind': 'R08 real browser/API/PG/worker and authorized OCR gateway', 'result': 'RUNNING',
              'frontend_source_sha256': digest.hexdigest(), 'input_pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(), 'checks': checks}

    def compose(*command, data=''):
        result = subprocess.run(['docker', 'compose', '-p', args.project, '-f', 'compose.yaml', '-f', 'frontend/tests/compose.r08.yaml', *command],
                                cwd=root, input=data, text=True, encoding='utf-8', capture_output=True)
        if result.returncode:
            raise RuntimeError('Compose operation failed: ' + command[0])
        return result.stdout

    def fixture(action):
        return json.loads(compose('exec', '-T', 'api', 'python', '/srv/r08/material_fixture.py', action,
                                  data=json.dumps({'password': password}) if action == 'seed' else ''))

    event_id = fixture('seed')['event_id']

    def passed(name):
        checks.append({'check': name, 'result': 'PASS'})
        print('PASS ' + name, flush=True)

    with sync_playwright() as engine:
        browser = engine.chromium.launch(headless=True, channel=args.channel)
        admin_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        user_context = browser.new_context()
        anonymous = browser.new_context()
        page = admin_context.new_page()
        user = user_context.new_page()
        for tab in [page, user]:
            tab.on('pageerror', lambda error: errors.append(type(error).__name__))
        page.on('request', lambda request: mutations.append((request.method, urlsplit(request.url).path)) if request.method in {'POST', 'PATCH'} and '/api/admin/' in request.url else None)

        def login(tab, email):
            tab.get_by_label('Email', exact=True).fill(email)
            tab.get_by_label('Пароль', exact=True).fill(password)
            tab.get_by_role('button', name='Войти', exact=True).click()

        def headers():
            return {'X-CSRF-Token': admin_context.request.get(base + '/api/me').json()['csrf_token']}

        def feed():
            return user_context.request.get(base + '/api/companies/demo_company_a/feed').json()['items']

        try:
            page.goto(base + '/admin/documents'); login(page, 'admin@goat.example.org')
            expect(page.get_by_role('heading', name='Банковские PDF', exact=True)).to_be_visible()
            page.get_by_label('PDF-файл', exact=True).set_input_files({'name': 'bad.pdf', 'mimeType': 'application/pdf', 'buffer': b'not-pdf'})
            page.get_by_role('button', name='Загрузить и проиндексировать', exact=True).click()
            expect(page.get_by_role('region', name='Текущая обработка').get_by_role('alert')).to_be_visible()
            assert not mutations
            passed('invalid PDF header is rejected locally without upload or fake success')

            page.get_by_label('PDF-файл', exact=True).set_input_files(pdf)
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/api/admin/documents')) as response:
                page.get_by_role('button', name='Загрузить и проиндексировать', exact=True).click()
            assert response.value.status == 202
            upload = response.value.json()
            report['document_id'] = upload['document']['id']
            report['job_id'] = upload['job']['id']
            print('Real PDF upload accepted; waiting for OCR/index job', flush=True)
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                status = admin_context.request.get(base + '/api/jobs/' + upload['job']['id']).json()
                if status['status'] == 'failed':
                    raise AssertionError('Real OCR failed: ' + str(status.get('error', {}).get('code')))
                if status['status'] == 'done':
                    break
                retry = page.get_by_role('region', name='Текущая обработка').get_by_role('button', name='Повторить', exact=True)
                if retry.count() and retry.is_visible():
                    retry.click()
                page.wait_for_timeout(2000)
            else:
                raise AssertionError('OCR job did not finish within the acceptance window')
            source_button = page.get_by_role('button', name='Основание загруженного PDF', exact=True)
            if not source_button.count():
                retry = page.get_by_role('region', name='Текущая обработка').get_by_role('button', name='Повторить', exact=True)
                if retry.count():
                    retry.click()
            expect(source_button).to_be_visible(timeout=20_000)
            source_button.click()
            source_id = status['result']['source_id']
            source = admin_context.request.get(base + '/api/sources/' + source_id).json()
            assert source['locator']['page'] == 1 and len(source['excerpt']) > 20
            assert source['source_id'] == upload['document']['id']
            expect(page.get_by_role('link', name='Открыть защищённый PDF · страница 1 ↗', exact=True)).to_be_visible()
            content = admin_context.request.get(base + '/api/sources/' + source_id + '/file')
            assert content.status == 200 and hashlib.sha256(content.body()).hexdigest() == report['input_pdf_sha256']
            assert anonymous.request.get(base + '/api/sources/' + source_id + '/file').status == 401
            counts = fixture('counts')
            assert counts['chunks'] >= 3
            report.update(chunks=counts['chunks'], source_id=source_id, document_date=source['locator'].get('document_date'))
            page.screenshot(path=str(args.output / 'documents-desktop.png'), full_page=True)
            passed('provided PDF passes real upload → worker → OCR → index → persisted page evidence and authorized original file')

            before = counts['jobs']
            page.get_by_role('button', name='Загрузить и проиндексировать', exact=True).click()
            expect(page.get_by_text('Документ уже обработан. Новое задание не создавалось.', exact=True)).to_be_visible()
            assert fixture('counts')['jobs'] == before
            passed('re-upload of identical bytes reuses the document and indexed evidence without a new job')

            user.goto(base + '/app/companies'); login(user, 'user_a@goat.example.org')
            expect(user.get_by_role('heading', name='Компании и профиль', exact=True)).to_be_visible()
            assert any(row['event_id'] == event_id for row in feed())
            page.get_by_role('link', name='Новости', exact=True).click()
            row = page.get_by_role('article', name='Новость: Учебная новость R-08', exact=True)
            expect(row.get_by_role('list', name='Источники новости')).to_contain_text('Банк России')
            row.get_by_role('button', name='Скрыть для всех', exact=True).click()
            page.get_by_role('button', name='Подтвердить изменение', exact=True).click()
            expect(row.get_by_text('Скрыта для всех', exact=True)).to_be_visible()
            assert all(item['event_id'] != event_id for item in feed())
            row.get_by_role('button', name='Вернуть всем', exact=True).click()
            page.get_by_role('button', name='Подтвердить изменение', exact=True).click()
            expect(row.get_by_text('Видна пользователям', exact=True)).to_be_visible()
            assert any(item['event_id'] == event_id for item in feed())
            passed('operator visibility excludes/restores the event in another user feed globally')

            # Pause only this isolated worker to make active-job dedup deterministic.
            compose('stop', 'worker')
            page.get_by_role('link', name='PDF', exact=True).click()
            missing = page.get_by_role('article', name='Документ: Учебная ошибка PDF.pdf', exact=True)
            expect(missing.get_by_role('alert')).to_contain_text('not_found')
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/r08-missing-file/reindex')) as retry_response:
                missing.get_by_role('button', name='Повторить индексацию', exact=True).click()
            active_job = retry_response.value.json()
            duplicate = admin_context.request.post(base + '/api/admin/documents/r08-missing-file/reindex', headers=headers()).json()
            assert active_job['id'] == duplicate['id']
            compose('start', 'worker')
            expect(page.get_by_role('region', name='Текущая обработка').get_by_role('alert')).to_be_visible(timeout=30_000)
            failed = admin_context.request.get(base + '/api/jobs/' + active_job['id']).json()
            assert failed['status'] == 'failed' and failed['error']['code'] == 'not_found'
            compose('stop', 'worker')
            passed('a real missing-file worker failure is visible and repeated active reindex returns one job')

            page.get_by_role('link', name='Новости', exact=True).click()
            with page.expect_response(lambda response: response.url.endswith('/api/admin/jobs/collect-news')) as collection:
                page.get_by_role('button', name='Собрать новости', exact=True).click()
            collection_id = collection.value.json()['id']
            duplicate = admin_context.request.post(base + '/api/admin/jobs/collect-news', headers=headers()).json()
            assert duplicate['id'] == collection_id
            page.get_by_role('link', name='Задания', exact=True).click()
            collection_row = page.get_by_role('article', name='Задание: ' + collection_id, exact=True)
            expect(collection_row).to_contain_text('Сбор новостей')
            before_posts = len(mutations)
            collection_row.get_by_role('button', name='Проверить задание', exact=True).click()
            expect(page.get_by_role('region', name='Текущая обработка')).to_contain_text(collection_id)
            assert len(mutations) == before_posts
            passed('collect command deduplicates queued work; jobs identify operation/target and monitoring performs no POST')

            page.get_by_role('link', name='Новости', exact=True).click()
            row = page.get_by_role('article', name='Новость: Учебная новость R-08', exact=True)
            with page.expect_response(lambda response: response.url.endswith('/api/admin/news/' + event_id + '/retry')) as news_retry:
                row.get_by_role('button', name='Повторить обработку', exact=True).click()
            duplicate = admin_context.request.post(base + '/api/admin/news/' + event_id + '/retry', headers=headers()).json()
            assert duplicate['id'] == news_retry.value.json()['id']
            passed('explicit news retry uses the existing summarize queue and reuses its active job')

            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(args.output / 'news-mobile.png'), full_page=True)
            for path in ['/admin/documents', '/admin/news', '/admin/jobs']:
                user.goto(base + path)
                expect(user.get_by_role('alert')).to_contain_text('Нет доступа')
                assert user_context.request.get(base + '/api' + path).status == 403
                expect(user.locator('.access-card')).to_have_count(0)
            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            assert not errors
            passed('390px layout fits; ordinary user direct material/job routes and APIs remain forbidden; no browser storage secrets')
            report['result'] = 'PASS'
        except Exception:
            report['result'] = 'FAIL'
            page.screenshot(path=str(args.output / 'failure.png'), full_page=True)
            raise
        finally:
            # Leave queued news/collection unexecuted: gateway approval covers OCR only.
            compose('stop', 'worker')
            (args.output / 'browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            browser.close()


if __name__ == '__main__':
    main()

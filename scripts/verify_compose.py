"""Verify and recreate the explicitly named Compose stack, keeping its volumes.

Start the stack first with docker compose -p <project> up --build -d --wait.
Uses only Python's standard library; no provider keys or real client data.
"""
import argparse
import http.cookiejar
import json
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--report', type=Path, default=Path('artifacts/r02-compose.json'))
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', args.project):
        parser.error('Use an explicit lowercase Compose project name.')
    root = Path(__file__).resolve().parents[1]
    checks = []

    def compose(*command):
        result = subprocess.run(
            ['docker', 'compose', '-p', args.project, *command], cwd=root,
            capture_output=True, text=True, encoding='utf-8',
        )
        if result.returncode:
            raise RuntimeError(f'Compose {command[0]} failed: {result.stderr[-1800:]}')
        return result.stdout

    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))

    def http(method, path, body=None, csrf=None):
        headers = {'Origin': args.base_url, 'Accept': 'application/json'}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        if csrf:
            headers['X-CSRF-Token'] = csrf
        request = urllib.request.Request(
            args.base_url.rstrip('/') + path, method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        try:
            response = opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            text = response.read().decode()
            return response.status, json.loads(text) if text else None

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append({'check': name, 'result': 'PASS'})
        print(f'PASS {name}', flush=True)

    def services():
        text = compose('ps', '--format', 'json')
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        return data if isinstance(data, list) else [data]

    report = {'project': args.project, 'kind': 'live four-service Compose acceptance', 'checks': checks}
    try:
        before = services()
        check('exactly web/api/worker/postgres are running', {item['Service'] for item in before} == {'web', 'api', 'worker', 'postgres'} and all(item['State'] == 'running' for item in before))
        check('all four services are healthy', all(item.get('Health') == 'healthy' for item in before))
        status, health = http('GET', '/health')
        check('GET /health returns 200 through nginx', status == 200 and health == {'status': 'ok'})
        status, schema = http('GET', '/api/openapi.json')
        check('OpenAPI is served through the API proxy', status == 200 and '/auth/login' in schema.get('paths', {}))
        status, schema = http('GET', '/openapi.json')
        check('Swagger absolute OpenAPI URL is proxied', status == 200 and '/auth/login' in schema.get('paths', {}))
        for path in ['/login', '/register', '/app', '/app/analytics', '/admin']:
            with opener.open(args.base_url.rstrip('/') + path, timeout=10) as response:
                check(f'SPA direct URL {path}', response.status == 200 and 'id="root"' in response.read().decode())

        compose('exec', '-T', 'api', 'python', '-m', 'app.cli', 'migrate')
        compose('exec', '-T', 'api', 'python', '-m', 'app.cli', 'seed-demo')
        compose('exec', '-T', 'api', 'python', '-m', 'app.cli', 'seed-demo')
        check('migration and repeated seed succeed', True)

        identity = uuid.uuid4().hex
        password = secrets.token_urlsafe(24)
        credentials = {'email': f'r02-{identity}@example.org', 'password': password}
        status, user = http('POST', '/api/auth/register', credentials)
        check('synthetic record created in PostgreSQL', status == 201 and user['system_role'] == 'user')
        status, session = http('POST', '/api/auth/login', credentials)
        check('real backend login succeeds through proxy', status == 200 and session['id'] == user['id'])
        check('backend session cookie is HttpOnly', any(cookie.name == 'goat_session' and cookie.has_nonstandard_attr('HttpOnly') for cookie in cookies))
        status, _ = http('POST', '/api/auth/logout')
        check('mutation without CSRF is rejected', status == 403)
        status, _ = http('GET', '/api/admin/stats')
        check('ordinary account cannot read admin stats', status == 403)

        filename = f'r02-persistence-{identity}.txt'
        marker = f'synthetic-{identity}'
        write = f"from pathlib import Path; import os; (Path(os.environ['STORAGE_DIR'])/{filename!r}).write_text({marker!r}, encoding='utf-8')"
        read = f"from pathlib import Path; import os; assert (Path(os.environ['STORAGE_DIR'])/{filename!r}).read_text(encoding='utf-8') == {marker!r}"
        compose('exec', '-T', 'api', 'python', '-c', write)
        compose('exec', '-T', 'worker', 'python', '-c', read)
        check('non-root API can write shared document volume and worker can read it', True)

        compose('down', '--remove-orphans')
        compose('up', '-d', '--wait', '--wait-timeout', '180')
        after = services()
        check('containers recreated without deleting volumes', len(after) == 4 and not ({item['ID'] for item in before} & {item['ID'] for item in after}))
        status, health = http('GET', '/health')
        check('health restored after recreation', status == 200 and health == {'status': 'ok'})
        status, restored = http('GET', '/api/me')
        check('user record and server session survive recreation', status == 200 and restored['id'] == user['id'])
        compose('exec', '-T', 'api', 'python', '-c', read)
        compose('exec', '-T', 'worker', 'python', '-c', read)
        check('document data survives recreation in both services', True)
        status, _ = http('POST', '/api/auth/logout', csrf=restored['csrf_token'])
        check('mutation with restored CSRF succeeds', status == 204)
        status, _ = http('GET', '/api/me')
        check('logout revokes the persisted session', status == 401)
        report['result'] = 'PASS'
    except Exception as error:
        report.update(result='FAIL', error=str(error))
    report_path = args.report if args.report.is_absolute() else root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Result: {report['result']}; report: {args.report}", flush=True)
    if report['result'] != 'PASS':
        print(report['error'], file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()

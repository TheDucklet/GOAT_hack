"""Check the optional AI handoff using synthetic values, without starting services."""
import json
import os
import subprocess
import uuid
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    probe = root / f'.env.r02-probe-{uuid.uuid4().hex}'
    try:
        probe.write_text('AI_MODULE=app.ai.pending\nAI_GENERATION_VERSION=r02-probe\nR02_PROVIDER_SENTINEL=synthetic-not-a-key\n', encoding='utf-8')
        result = subprocess.run(
            ['docker', 'compose', 'config', '--format', 'json'], cwd=root,
            env={**os.environ, 'AI_ENV_FILE': str(probe)},
            text=True, encoding='utf-8', capture_output=True, check=True,
        )
        services = json.loads(result.stdout)['services']
        assert set(services) == {'web', 'api', 'worker', 'postgres'}
        for name in ['api', 'worker']:
            assert services[name]['environment']['R02_PROVIDER_SENTINEL'] == 'synthetic-not-a-key'
            assert services[name]['environment']['AI_MODULE'] == 'app.ai.pending'
        for name in ['web', 'postgres']:
            assert 'R02_PROVIDER_SENTINEL' not in services[name].get('environment', {})
            assert 'AI_MODULE' not in services[name].get('environment', {})
        assert 'app.worker' in services['worker']['command']
        assert 'app.worker' not in ' '.join(services['api']['command'])
        mounts = [next(mount for mount in services[name]['volumes'] if mount['target'] == '/srv/backend/storage')['source'] for name in ['api', 'worker']]
        assert mounts[0] == mounts[1]
        print('PASS exactly four services, scheduler command only in worker')
        print('PASS api/worker share the document volume')
        print('PASS optional future AI variables reach api/worker without Compose edits')
        print('PASS AI variables are absent from web and PostgreSQL')
    finally:
        probe.unlink(missing_ok=True)


if __name__ == '__main__':
    main()

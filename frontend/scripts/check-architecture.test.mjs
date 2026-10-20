import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

const checker = resolve(dirname(fileURLToPath(import.meta.url)), 'check-architecture.mjs');
function fixture(files) {
  const root = mkdtempSync(resolve(tmpdir(), 'goat-architecture-'));
  try {
    for (const [name, content] of Object.entries(files)) {
      const path = resolve(root, name);
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(path, content);
    }
    const result = spawnSync(process.execPath, [checker, '--root', root], { encoding: 'utf8' });
    return { status: result.status, report: JSON.parse(result.stdout) };
  } finally {
    // Verify the absolute deletion target is the exact temporary fixture directory.
    assert.equal(dirname(resolve(root)), resolve(tmpdir()));
    assert.ok(basename(root).startsWith('goat-architecture-'));
    rmSync(root, { recursive: true });
  }
}

test('a shared-to-feature import and a cycle are both rejected', () => {
  const result = fixture({ 'shared/a.ts': "import '../features/auth/a';", 'features/auth/a.ts': "import '../../shared/a';" });
  assert.equal(result.status, 1);
  assert.ok(result.report.violations.some((item) => item.startsWith('Shared imports')));
  assert.ok(result.report.violations.some((item) => item.startsWith('Import cycle')));
});
test('valid app -> feature -> shared dependencies are accepted', () => {
  const result = fixture({ 'shared/a.ts': 'export const value = 1;', 'features/auth/a.ts': "import '../../shared/a';", 'app/App.ts': "import '../features/auth/a';" });
  assert.equal(result.status, 0);
  assert.equal(result.report.runtime_modules, 3);
  assert.deepEqual(result.report.violations, []);
});
test('type-only imports do not create runtime cycles', () => {
  const result = fixture({ 'shared/a.ts': "import { type B } from './b'; export interface A { b: B }", 'shared/b.ts': "import { type A } from './a'; export interface B { a: A }" });
  assert.equal(result.status, 0);
  assert.equal(result.report.runtime_import_edges, 0);
});

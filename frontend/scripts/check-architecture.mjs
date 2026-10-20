// Uses the installed TypeScript parser; no additional dependency or alias config.
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const rootArg = process.argv.indexOf('--root');
const root = rootArg >= 0 ? resolve(process.argv[rootArg + 1]) : resolve(dirname(fileURLToPath(import.meta.url)), '../src');
const files = [];
function walk(directory) {
  for (const item of readdirSync(directory, { withFileTypes: true })) {
    const path = resolve(directory, item.name);
    if (item.isDirectory()) walk(path);
    else if (/\.tsx?$/.test(path) && !/\.d\.ts$|\.test\.tsx?$/.test(path) && !path.includes(resolve(root, 'shared/test'))) files.push(path);
  }
}
walk(root);
const graph = new Map(files.map((path) => [path, new Set()]));
const violations = [];
const allowed = { companies: ['auth'], analytics: ['companies'], overview: ['companies'] };
const local = (path) => relative(root, path).replaceAll('\\', '/');
function resolveImport(owner, specifier) {
  const base = resolve(dirname(owner), specifier);
  return [base, `${base}.ts`, `${base}.tsx`, `${base}.d.ts`, resolve(base, 'index.ts')].find(existsSync);
}
for (const path of files) {
  const source = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true);
  function check(specifier, typeOnly = false) {
    if (!specifier.startsWith('.')) return;
    const target = resolveImport(path, specifier);
    if (!target) { violations.push(`Missing import: ${local(path)} -> ${specifier}`); return; }
    const from = local(path).split('/');
    const to = local(target).split('/');
    if (from[0] === 'shared' && ['features', 'app'].includes(to[0])) violations.push(`Shared imports application code: ${local(path)} -> ${local(target)}`);
    if (from[0] === 'features' && to[0] === 'app') violations.push(`Feature imports composition/layout: ${local(path)} -> ${local(target)}`);
    if (from[0] === 'features' && to[0] === 'features' && from[1] !== to[1] && !(allowed[from[1]] || []).includes(to[1])) violations.push(`Unapproved feature dependency: ${local(path)} -> ${local(target)}`);
    if (!typeOnly && graph.has(target)) graph.get(path).add(target);
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const clause = node.importClause;
      const names = clause?.namedBindings;
      const namedTypesOnly = !clause?.name && names && ts.isNamedImports(names) && names.elements.length > 0 && names.elements.every((item) => item.isTypeOnly);
      check(node.moduleSpecifier.text, clause?.isTypeOnly || namedTypesOnly);
    }
    if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) check(node.moduleSpecifier.text, node.isTypeOnly);
    if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) check(node.arguments[0].text);
    ts.forEachChild(node, visit);
  }
  visit(source);
}
const active = new Set();
const finished = new Set();
const stack = [];
function visit(path) {
  if (active.has(path)) { violations.push(`Import cycle: ${[...stack.slice(stack.indexOf(path)), path].map(local).join(' -> ')}`); return; }
  if (finished.has(path)) return;
  active.add(path); stack.push(path);
  for (const target of graph.get(path)) visit(target);
  stack.pop(); active.delete(path); finished.add(path);
}
for (const path of files) visit(path);
const result = { result: violations.length ? 'FAIL' : 'PASS', runtime_modules: files.length, runtime_import_edges: [...graph.values()].reduce((sum, edges) => sum + edges.size, 0), violations };
console.log(JSON.stringify(result, null, 2));
process.exitCode = violations.length ? 1 : 0;

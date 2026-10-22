import { expect, it, vi } from 'vitest';
import { HttpClient, type Transport } from '../../shared/api/http';
import { demoMe } from '../../shared/api/mock/fixtures';
import { createAdminApi } from './api';

it('uses the existing transport, cookie/CSRF and encoded identifiers for admin reads and status changes', async () => {
  const transport = vi.fn<Transport>().mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith('/me') ? demoMe : [])));
  const api = createAdminApi(new HttpClient('/api', transport));
  await api.users(undefined, 50, 100);
  await api.memberships(undefined, 50, 50);
  await api.updateUser('person/1', { status: 'blocked' });
  await api.updateMembership('member/1', { status: 'active' });
  expect(transport.mock.calls.map(([input]) => input)).toEqual(['/api/admin/users?limit=50&offset=100', '/api/admin/memberships?limit=50&offset=50', '/api/me', '/api/admin/users/person%2F1', '/api/admin/memberships/member%2F1']);
  for (const [, init] of transport.mock.calls) expect(init?.credentials).toBe('include');
  for (const [, init] of transport.mock.calls.filter(([, init]) => init?.method === 'PATCH')) expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe(demoMe.csrf_token);
  expect(JSON.parse(String(transport.mock.calls[3]![1]!.body))).toEqual({ status: 'blocked' });
});

it('uploads native multipart without a Content-Type boundary override and reuses CSRF for material commands', async () => {
  const transport = vi.fn<Transport>().mockImplementation(async (input) => new Response(JSON.stringify(String(input).endsWith('/me') ? demoMe : {})));
  const api = createAdminApi(new HttpClient('/api', transport));
  const file = new File(['%PDF-test'], 'bank.pdf', { type: 'application/pdf' });
  await api.upload(file);
  await api.reindex('doc/1'); await api.retryNews('event/1'); await api.collectNews();
  const [, upload] = transport.mock.calls[1]!;
  expect(upload?.body).toBeInstanceOf(FormData);
  expect(new Headers(upload?.headers).has('Content-Type')).toBe(false);
  expect(new Headers(upload?.headers).get('X-CSRF-Token')).toBe(demoMe.csrf_token);
  expect(transport.mock.calls.slice(2).map(([input]) => input)).toEqual(['/api/admin/documents/doc%2F1/reindex', '/api/admin/news/event%2F1/retry', '/api/admin/jobs/collect-news']);
});

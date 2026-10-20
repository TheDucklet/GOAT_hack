import type { Transport } from '../client';
import { demoChat, demoCompanies, demoError, demoFeed, demoInsight, demoJob, demoMe, demoPassword, demoStats, demoUser } from './fixtures';
import type { ApiErrorBody, Credentials, Me } from '../types';

export interface MockSessionStore {
  get(): string | null;
  set(value: string | null): void;
}

// This cookie contains only a mock identity; real sessions are HttpOnly backend cookies.
const cookieStore: MockSessionStore = {
  get: () => document.cookie.split('; ').find((part) => part.startsWith('goat_mock_identity='))?.split('=')[1] || null,
  set: (value) => { document.cookie = `goat_mock_identity=${value || ''}; Path=/; SameSite=Lax; Max-Age=${value ? 3600 : 0}`; },
};

export function createMockTransport(store: MockSessionStore = cookieStore): Transport {
  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  const error = (status: number, code: string, message: string, field_errors: ApiErrorBody['field_errors'] = []) =>
    json({ ...demoError, code, message, request_id: `mock-${code}`, field_errors } satisfies ApiErrorBody, status);
  const session = (email: string): Me => ({
    ...structuredClone(demoMe),
    email, system_role: email === 'admin@example.org' ? 'admin' : 'user',
  });

  return async (input, init = {}) => {
    if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError');
    const url = new URL(String(input), 'http://localhost');
    // Accept both a relative /api base and an absolute configurable base.
    const path = url.pathname.replace(/^\/api(?=\/|$)/, '');
    const method = (init.method || 'GET').toUpperCase();
    let body: Record<string, unknown> = {};
    if (typeof init.body === 'string') {
      try { body = JSON.parse(init.body) as Record<string, unknown>; }
      catch { return error(422, 'validation_error', 'Неверный JSON.'); }
    }
    if (method === 'POST' && ['/auth/login', '/auth/register'].includes(path)) {
      const credentials = body as unknown as Credentials;
      const fields: NonNullable<ApiErrorBody['field_errors']> = [];
      const minimum = path === '/auth/register' ? 10 : 1;
      if (typeof credentials.email !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(credentials.email)) fields.push({ loc: ['body', 'email'], message: 'Введите корректный email.', type: 'value_error' });
      if (typeof credentials.password !== 'string' || credentials.password.length < minimum || credentials.password.length > 256) fields.push({ loc: ['body', 'password'], message: `Пароль должен содержать от ${minimum} до 256 символов.`, type: 'string_length' });
      if (fields.length) return error(422, 'validation_error', 'Проверьте поля.', fields);
      if (credentials.email === 'unavailable@example.org') return error(503, 'service_unavailable', 'Сервис временно недоступен.');
      if (credentials.email === 'blocked@example.org') return error(403, 'user_blocked', 'Нет доступа');
      if (path === '/auth/register') {
        if (credentials.email === demoMe.email) return error(409, 'email_taken', 'Email уже занят.');
        return json({ ...demoUser, id: 'new-user', email: credentials.email }, 201);
      }
      if (![demoMe.email, 'admin@example.org'].includes(credentials.email) || credentials.password !== demoPassword) return error(401, 'invalid_credentials', 'Неверный email или пароль.');
      store.set(credentials.email);
      return json(session(credentials.email));
    }
    const identity = store.get();
    if (!identity) return error(401, 'unauthenticated', 'Необходим вход.');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && new Headers(init.headers).get('X-CSRF-Token') !== demoMe.csrf_token) return error(403, 'csrf_invalid', 'Нет доступа');
    if (path.startsWith('/admin') && identity !== 'admin@example.org') return error(403, 'forbidden', 'Нет доступа');
    if (path === '/me' && method === 'GET') return json(session(identity));
    if (path === '/auth/logout' && method === 'POST') { store.set(null); return new Response(null, { status: 204 }); }
    if (path === '/companies' && method === 'GET') return json(demoCompanies);
    if (path === '/admin/stats' && method === 'GET') return json(demoStats);
    const companyPath = /^\/companies\/([^/]+)\/(feed|insights)$/.exec(path);
    if (companyPath && companyPath[1] !== demoChat.company_id) return error(403, 'forbidden', 'Нет доступа');
    if (companyPath?.[2] === 'feed' && method === 'GET') {
      const limit = Math.max(1, Number(url.searchParams.get('limit') || 20));
      const offset = Math.max(0, Number(url.searchParams.get('offset') || 0));
      return json({ ...demoFeed, limit, offset, items: demoFeed.items.slice(offset, offset + limit) });
    }
    if (companyPath?.[2] === 'insights' && method === 'POST') return json(demoJob, 202);
    if (path === `/insights/${demoInsight.id}` && method === 'GET') return json(demoInsight);
    if (path === '/chats' && method === 'POST') {
      if (body.company_id !== demoChat.company_id) return error(403, 'forbidden', 'Нет доступа');
      return json(demoChat, 201);
    }
    if (path === `/chats/${demoChat.id}/messages`) return method === 'POST' ? json(demoJob, 202) : json([]);
    if (path === `/jobs/${demoJob.id}` && method === 'GET') return json(demoJob);
    return error(404, 'not_found', 'Тестовый маршрут не найден.');
  };
}

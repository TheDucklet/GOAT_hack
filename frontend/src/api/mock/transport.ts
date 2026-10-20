import type { Transport } from '../client';
import { demoChat, demoCompanies, demoError, demoFeed, demoInsight, demoJob, demoMe, demoPassword, demoStats, demoUser } from './fixtures';
import type { ApiErrorBody, Credentials, Me, Membership } from '../types';

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
  const registrations = new Map<string, { id: string; password: string }>();
  const memberships = new Map<string, Membership[]>();
  const session = (email: string): Me => ({
    ...structuredClone(demoMe),
    id: registrations.get(email)?.id || demoMe.id,
    memberships: structuredClone(memberships.get(email) || (registrations.has(email) ? [] : demoMe.memberships)),
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
        if ([demoMe.email, 'admin@example.org'].includes(credentials.email) || registrations.has(credentials.email)) return error(409, 'email_exists', 'Email уже зарегистрирован.');
        const id = `mock-user-${registrations.size + 1}`;
        registrations.set(credentials.email, { id, password: credentials.password });
        return json({ ...demoUser, id, email: credentials.email }, 201);
      }
      const password = registrations.get(credentials.email)?.password || ([demoMe.email, 'admin@example.org'].includes(credentials.email) ? demoPassword : null);
      if (credentials.password !== password) return error(401, 'invalid_credentials', 'Неверный email или пароль.');
      store.set(credentials.email);
      return json(session(credentials.email));
    }
    const identity = store.get();
    if (!identity) return error(401, 'unauthenticated', 'Необходим вход.');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && new Headers(init.headers).get('X-CSRF-Token') !== demoMe.csrf_token) return error(403, 'csrf_invalid', 'Нет доступа');
    if (path.startsWith('/admin') && identity !== 'admin@example.org') return error(403, 'forbidden', 'Нет доступа');
    if (path === '/me' && method === 'GET') return json(session(identity));
    if (path === '/auth/logout' && method === 'POST') { store.set(null); return new Response(null, { status: 204 }); }
    if (path === '/companies' && method === 'GET') return json(demoCompanies.filter((company) => session(identity).memberships.some((membership) => membership.status === 'active' && membership.company_id === company.id)));
    const profilePath = /^\/memberships\/([^/]+)\/profile$/.exec(path);
    if ((path === '/memberships/requests' && method === 'POST') || (profilePath && method === 'PATCH')) {
      const fields: NonNullable<ApiErrorBody['field_errors']> = [];
      if (typeof body.position_text !== 'string' || body.position_text.length > 1000) fields.push({ loc: ['body', 'position_text'], message: 'Должность должна содержать не более 1000 символов.', type: 'string_length' });
      if (!Array.isArray(body.interests) || body.interests.length > 30 || body.interests.some((item) => typeof item !== 'string')) fields.push({ loc: ['body', 'interests'], message: 'Укажите не более 30 тем.', type: 'list_length' });
      if (!profilePath && (typeof body.company_id !== 'string' || !body.company_id.length || body.company_id.length > 100)) fields.push({ loc: ['body', 'company_id'], message: 'Укажите идентификатор компании, до 100 символов.', type: 'string_length' });
      if (fields.length) return error(422, 'validation_error', 'Проверьте поля.', fields);
      const current = session(identity);
      const own = current.memberships;
      const profile = { position_text: body.position_text as string, interests: body.interests as string[] };
      let result: Membership;
      if (profilePath) {
        const existing = own.find((item) => item.id === decodeURIComponent(profilePath[1]!));
        if (!existing) return error(403, 'forbidden', 'Нельзя изменить чужое членство');
        result = { ...existing, ...profile };
      } else {
        if (!demoCompanies.some((item) => item.id === body.company_id)) return error(404, 'not_found', 'Компания не найдена');
        if (own.some((item) => item.company_id === body.company_id)) return error(409, 'membership_exists', 'Членство или заявка уже существует');
        result = { id: `mock-membership-${current.id}-${own.length}`, user_id: current.id, company_id: body.company_id as string, ...profile, status: 'pending' };
      }
      memberships.set(identity, [...own.filter((item) => item.id !== result.id), result]);
      return json(result, profilePath ? 200 : 201);
    }
    if (path === '/admin/stats' && method === 'GET') return json(demoStats);
    const companyPath = /^\/companies\/([^/]+)\/(feed|insights)$/.exec(path);
    if (companyPath && !session(identity).memberships.some((item) => item.company_id === companyPath[1] && item.status === 'active')) return error(403, 'forbidden', 'Нет доступа');
    if (companyPath?.[2] === 'feed' && method === 'GET') {
      const limit = Math.max(1, Number(url.searchParams.get('limit') || 20));
      const offset = Math.max(0, Number(url.searchParams.get('offset') || 0));
      return json({ ...demoFeed, limit, offset, items: demoFeed.items.slice(offset, offset + limit) });
    }
    if (companyPath?.[2] === 'insights' && method === 'POST') return json(demoJob, 202);
    if (path === `/insights/${demoInsight.id}` && method === 'GET') return json(demoInsight);
    if (path === '/chats' && method === 'POST') {
      if (!session(identity).memberships.some((item) => item.company_id === body.company_id && item.status === 'active')) return error(403, 'forbidden', 'Нет доступа');
      return json(demoChat, 201);
    }
    if (path === `/chats/${demoChat.id}/messages`) return method === 'POST' ? json(demoJob, 202) : json([]);
    if (path === `/jobs/${demoJob.id}` && method === 'GET') return json(demoJob);
    return error(404, 'not_found', 'Тестовый маршрут не найден.');
  };
}

import { describe, expect, it, vi } from 'vitest';
import { ApiClient, type Transport } from './client';
import { ApiError } from './errors';
import { demoFeed, demoMe } from './mock/fixtures';
import { createMockTransport, type MockSessionStore } from './mock/transport';

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe('API session and transport contract', () => {
  it('uses the configured base URL and cookie credentials, including public auth requests', async () => {
    const fetcher = vi.fn<Transport>().mockResolvedValue(response(demoMe));
    const client = new ApiClient('https://api.example.test/v1/', fetcher);
    await client.login({ email: 'demo@example.org', password: 'test-value' });
    expect(fetcher).toHaveBeenCalledWith('https://api.example.test/v1/auth/login', expect.objectContaining({ credentials: 'include', method: 'POST' }));
    const init = fetcher.mock.calls[0]![1]!;
    expect(new Headers(init.headers).has('X-CSRF-Token')).toBe(false);
  });

  it('reads CSRF from /me before a mutation and keeps it in memory', async () => {
    const fetcher = vi.fn<Transport>()
      .mockResolvedValueOnce(response(demoMe))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient('/api', fetcher);
    await client.logout();
    expect(fetcher.mock.calls[0]![0]).toBe('/api/me');
    const init = fetcher.mock.calls[1]![1]!;
    expect(new Headers(init.headers).get('X-CSRF-Token')).toBe(demoMe.csrf_token);
    expect(init.credentials).toBe('include');
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it('uses the login CSRF and replaces it after /me', async () => {
    const fetcher = vi.fn<Transport>()
      .mockResolvedValueOnce(response(demoMe))
      .mockResolvedValueOnce(response({ ...demoMe, csrf_token: 'rotated-token' }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    const client = new ApiClient('/api', fetcher);
    await client.login({ email: demoMe.email, password: 'test-value' });
    await client.me();
    await client.logout();
    expect(new Headers(fetcher.mock.calls[2]![1]!.headers).get('X-CSRF-Token')).toBe('rotated-token');
  });

  it.each([401, 403, 422, 503])('keeps the %i status and structured error fields', async (status) => {
    const body = { code: 'error', message: 'Message', request_id: 'req-1', field_errors: [{ loc: ['body', 'email'], message: 'Invalid email', type: 'value_error' }] };
    const client = new ApiClient('/api', async () => response(body, status));
    await expect(client.me()).rejects.toMatchObject({ status, body });
  });

  it('notifies the session owner on a protected 401, but not failed login', async () => {
    const fetcher = vi.fn<Transport>().mockImplementation(async () => response({}, 401));
    const client = new ApiClient('/api', fetcher);
    const listener = vi.fn();
    const unsubscribe = client.onUnauthorized(listener);
    await expect(client.login({ email: 'x', password: 'x' })).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
    await expect(client.companies()).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
    await expect(client.companies()).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledOnce();
  });

  it('preserves a 503 when a proxy returns HTML and never switches to mock', async () => {
    const fetcher = vi.fn<Transport>().mockResolvedValue(new Response('<html>Unavailable</html>', { status: 503 }));
    const client = new ApiClient('/api', fetcher);
    await expect(client.companies()).rejects.toMatchObject({ status: 503 });
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it('reports network errors and malformed success responses', async () => {
    await expect(new ApiClient('/api', async () => { throw new TypeError('Failed to fetch'); }).me()).rejects.toMatchObject({ status: 0 });
    await expect(new ApiClient('/api', async () => new Response('<html>Wrong proxy</html>')).me()).rejects.toMatchObject({ status: 502 });
  });

  it('passes cancellation through without turning it into a service error', async () => {
    const controller = new AbortController();
    controller.abort();
    const client = new ApiClient('/api', createMockTransport());
    await expect(client.companies(controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  });
});

describe('mock uses the same client and checks access and CSRF', () => {
  function makeMock(identity: string | null = null) {
    let current = identity;
    const store: MockSessionStore = { get: () => current, set: (value) => { current = value; } };
    const transport = createMockTransport(store);
    return { client: new ApiClient('/api', transport), transport };
  }

  it('restores the synthetic session and returns typed feed/job fixtures', async () => {
    const { client } = makeMock(demoMe.email);
    expect(await client.me()).toEqual(demoMe);
    expect(await client.feed('demo_company_a')).toEqual(demoFeed);
    expect(await client.buildInsight('demo_company_a', 'event-1')).toMatchObject({ id: 'example-job', status: 'queued' });
    expect(await client.job('example-job')).toMatchObject({ id: 'example-job' });
    expect(await client.createChat('demo_company_a', 'event-1')).toMatchObject({ id: 'example-chat' });
    expect(await client.insight('example-insight')).toMatchObject({ result: { bank_view: null } });
    await expect(client.feed('foreign-company')).rejects.toMatchObject({ status: 403 });
    await client.logout();
    await expect(client.me()).rejects.toMatchObject({ status: 401 });
  });

  it('denies ordinary users direct admin requests and rejects missing CSRF', async () => {
    const { client, transport } = makeMock(demoMe.email);
    await expect(client.adminStats()).rejects.toMatchObject({ status: 403 });
    const result = await transport('/api/auth/logout', { method: 'POST' });
    expect(result.status).toBe(403);
    expect(await client.me()).toEqual(demoMe);
  });
});

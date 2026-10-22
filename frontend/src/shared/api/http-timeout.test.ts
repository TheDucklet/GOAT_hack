import { afterEach, expect, it, vi } from 'vitest';
import { HttpClient, type Transport } from './http';

afterEach(() => { vi.useRealTimers(); });
const hanging: Transport = (_input, init) => new Promise((_resolve, reject) => {
  init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true });
});

it('bounds a stalled HTTP request and leaves the caller signal available for a safe manual retry', async () => {
  vi.useFakeTimers();
  const client = new HttpClient('/api', hanging);
  const owner = new AbortController();
  const result = expect(client.request('/jobs/pending', { signal: owner.signal, timeoutMs: 15000 })).rejects.toMatchObject({ status: 0, body: { code: 'request_timeout' } });
  await vi.advanceTimersByTimeAsync(15000);
  await result;
  expect(owner.signal.aborted).toBe(false);
});

it('propagates cancellation on a context change without presenting it as a network timeout', async () => {
  const client = new HttpClient('/api', hanging);
  const owner = new AbortController();
  const result = expect(client.request('/chats/owned', { signal: owner.signal, timeoutMs: 15000 })).rejects.toMatchObject({ name: 'AbortError' });
  owner.abort();
  await result;
});

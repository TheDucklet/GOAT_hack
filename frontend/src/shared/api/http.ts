import { normalizeError } from './errors';
import type { Me } from './types';

export type Transport = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type RequestOptions = Omit<RequestInit, 'body' | 'credentials'> & {
  body?: unknown;
  public?: boolean;
  timeoutMs?: number;
};

export class HttpClient {
  private csrfToken: string | null = null;
  private unauthorizedListeners = new Set<() => void>();

  constructor(private baseUrl: string, private transport: Transport = fetch) {
    this.baseUrl = baseUrl.replace(/\/+$/, '');
  }

  onUnauthorized(listener: () => void) {
    this.unauthorizedListeners.add(listener);
    return () => { this.unauthorizedListeners.delete(listener); };
  }

  clearSession() { this.csrfToken = null; }
  setCsrfToken(token: string) { this.csrfToken = token; }
  url(path: string) { return `${this.baseUrl}${path}`; }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { body, public: isPublic = false, timeoutMs, ...init } = options;
    const method = (init.method || 'GET').toUpperCase();
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    const multipart = body instanceof FormData;
    if (multipart) headers.delete('Content-Type');
    else if (body !== undefined) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !isPublic) {
      if (!this.csrfToken) {
        const session = await this.request<Me>('/me', { signal: init.signal, timeoutMs });
        this.setCsrfToken(session.csrf_token);
      }
      if (!this.csrfToken) throw normalizeError(401, { message: 'Войдите снова.' });
      headers.set('X-CSRF-Token', this.csrfToken);
    }
    let response: Response;
    let text: string;
    const deadline = timeoutMs ? new AbortController() : null;
    let timedOut = false;
    const abort = () => deadline?.abort();
    if (init.signal?.aborted) abort();
    init.signal?.addEventListener('abort', abort, { once: true });
    const timer = timeoutMs ? setTimeout(() => { timedOut = true; deadline!.abort(); }, timeoutMs) : null;
    try {
      response = await this.transport(this.url(path), {
        ...init, method, headers, credentials: 'include',
        signal: deadline?.signal || init.signal,
        body: body === undefined ? undefined : multipart ? body : JSON.stringify(body),
      });
      text = await response.text();
    } catch (error) {
      if (timedOut) throw normalizeError(0, { code: 'request_timeout', message: 'Сервер не ответил вовремя. Повторите проверку вручную.' });
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw normalizeError(0, { code: 'network_error', message: 'Нет соединения с сервером.' });
    } finally {
      if (timer !== null) clearTimeout(timer);
      init.signal?.removeEventListener('abort', abort);
    }
    let data: unknown;
    try { data = text ? JSON.parse(text) : undefined; }
    catch { data = undefined; }
    if (!response.ok) {
      if (response.status === 401 && !isPublic) {
        this.clearSession();
        this.unauthorizedListeners.forEach((listener) => listener());
      }
      throw normalizeError(response.status, data);
    }
    if (text && data === undefined) throw normalizeError(502, { message: 'Сервер вернул некорректный ответ.' });
    return data as T;
  }

}

import { normalizeError } from './errors';
import type { AdminStats, Chat, Company, Credentials, Feed, Insight, Job, Me, Membership, MembershipProfile, MembershipRequest, Message, Registration, User } from './types';

export type Transport = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
type RequestOptions = Omit<RequestInit, 'body' | 'credentials'> & {
  body?: unknown;
  public?: boolean;
};

export class ApiClient {
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

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { body, public: isPublic = false, ...init } = options;
    const method = (init.method || 'GET').toUpperCase();
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (body !== undefined) headers.set('Content-Type', 'application/json');
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !isPublic) {
      if (!this.csrfToken) await this.me();
      if (!this.csrfToken) throw normalizeError(401, { message: 'Войдите снова.' });
      headers.set('X-CSRF-Token', this.csrfToken);
    }
    let response: Response;
    try {
      response = await this.transport(`${this.baseUrl}${path}`, {
        ...init, method, headers, credentials: 'include',
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw normalizeError(0, { code: 'network_error', message: 'Нет соединения с сервером.' });
    }
    const text = await response.text();
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

  async me(signal?: AbortSignal): Promise<Me> {
    const session = await this.request<Me>('/me', { signal });
    this.csrfToken = session.csrf_token;
    return session;
  }

  async login(credentials: Credentials): Promise<Me> {
    const session = await this.request<Me>('/auth/login', { method: 'POST', body: credentials, public: true });
    this.csrfToken = session.csrf_token;
    return session;
  }

  register(credentials: Registration) {
    return this.request<User>('/auth/register', { method: 'POST', body: credentials, public: true });
  }

  async logout() {
    await this.request<void>('/auth/logout', { method: 'POST' });
    this.clearSession();
  }

  companies(signal?: AbortSignal) { return this.request<Company[]>('/companies', { signal }); }
  requestMembership(body: MembershipRequest) {
    return this.request<Membership>('/memberships/requests', { method: 'POST', body });
  }
  updateProfile(id: string, body: MembershipProfile) {
    return this.request<Membership>(`/memberships/${encodeURIComponent(id)}/profile`, { method: 'PATCH', body });
  }
  feed(companyId: string, limit = 20, offset = 0, signal?: AbortSignal) {
    return this.request<Feed>(`/companies/${encodeURIComponent(companyId)}/feed?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`, { signal });
  }
  buildInsight(companyId: string, eventId: string) {
    return this.request<Insight | Job>(`/companies/${encodeURIComponent(companyId)}/insights`, { method: 'POST', body: { event_id: eventId } });
  }
  insight(id: string) { return this.request<Insight>(`/insights/${encodeURIComponent(id)}`); }
  createChat(companyId: string, eventId: string) {
    return this.request<Chat>('/chats', { method: 'POST', body: { company_id: companyId, event_id: eventId } });
  }
  sendMessage(id: string, text: string) {
    return this.request<Job>(`/chats/${encodeURIComponent(id)}/messages`, { method: 'POST', body: { text } });
  }
  messages(id: string) { return this.request<Message[]>(`/chats/${encodeURIComponent(id)}/messages`); }
  job(id: string, signal?: AbortSignal) { return this.request<Job>(`/jobs/${encodeURIComponent(id)}`, { signal }); }
  adminStats(signal?: AbortSignal) { return this.request<AdminStats>('/admin/stats', { signal }); }
}

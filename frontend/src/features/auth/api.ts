import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { Credentials, Me, Registration, User } from '../../shared/api/types';
export function createAuthApi(client: HttpClient) {
  return {
    async me(signal?: AbortSignal): Promise<Me> {
      const session = await client.request<Me>('/me', { signal });
      client.setCsrfToken(session.csrf_token); return session;
    },
    async login(credentials: Credentials): Promise<Me> {
      const session = await client.request<Me>('/auth/login', { method: 'POST', body: credentials, public: true });
      client.setCsrfToken(session.csrf_token); return session;
    },
    register(body: Registration) { return client.request<User>('/auth/register', { method: 'POST', body, public: true }); },
    async logout() { await client.request<void>('/auth/logout', { method: 'POST' }); client.clearSession(); },
  };
}
export const authApi = createAuthApi(http);

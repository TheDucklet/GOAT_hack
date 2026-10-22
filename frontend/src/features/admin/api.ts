import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { AdminStats, Membership, MembershipPatch, User, UserPatch } from '../../shared/api/types';
export function createAdminApi(client: HttpClient) {
  return {
    adminStats(signal?: AbortSignal) { return client.request<AdminStats>('/admin/stats', { signal, timeoutMs: 15000 }); },
    users(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<User[]>(`/admin/users?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    memberships(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<Membership[]>(`/admin/memberships?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    updateUser(id: string, body: Pick<UserPatch, 'status'>, signal?: AbortSignal) { return client.request<User>(`/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body, signal, timeoutMs: 15000 }); },
    updateMembership(id: string, body: MembershipPatch, signal?: AbortSignal) { return client.request<Membership>(`/admin/memberships/${encodeURIComponent(id)}`, { method: 'PATCH', body, signal, timeoutMs: 15000 }); },
  };
}
export const adminApi = createAdminApi(http);

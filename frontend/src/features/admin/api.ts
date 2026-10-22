import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { AdminJob, AdminNews, AdminStats, BankDocument, DocumentUpload, Job, Membership, MembershipPatch, User, UserPatch, Visibility } from '../../shared/api/types';
export function createAdminApi(client: HttpClient) {
  return {
    adminStats(signal?: AbortSignal) { return client.request<AdminStats>('/admin/stats', { signal, timeoutMs: 15000 }); },
    users(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<User[]>(`/admin/users?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    memberships(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<Membership[]>(`/admin/memberships?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    updateUser(id: string, body: Pick<UserPatch, 'status'>, signal?: AbortSignal) { return client.request<User>(`/admin/users/${encodeURIComponent(id)}`, { method: 'PATCH', body, signal, timeoutMs: 15000 }); },
    updateMembership(id: string, body: MembershipPatch, signal?: AbortSignal) { return client.request<Membership>(`/admin/memberships/${encodeURIComponent(id)}`, { method: 'PATCH', body, signal, timeoutMs: 15000 }); },
    documents(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<BankDocument[]>(`/admin/documents?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    upload(file: File, signal?: AbortSignal) { const body = new FormData(); body.append('file', file); return client.request<DocumentUpload>('/admin/documents', { method: 'POST', body, signal, timeoutMs: 60000 }); },
    reindex(id: string, signal?: AbortSignal) { return client.request<Job>(`/admin/documents/${encodeURIComponent(id)}/reindex`, { method: 'POST', signal, timeoutMs: 15000 }); },
    news(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<AdminNews[]>(`/admin/news?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    visibility(id: string, visible: boolean, signal?: AbortSignal) { return client.request<Visibility>(`/admin/news/${encodeURIComponent(id)}`, { method: 'PATCH', body: { visible }, signal, timeoutMs: 15000 }); },
    retryNews(id: string, signal?: AbortSignal) { return client.request<Job>(`/admin/news/${encodeURIComponent(id)}/retry`, { method: 'POST', signal, timeoutMs: 15000 }); },
    jobs(signal?: AbortSignal, limit = 100, offset = 0) { return client.request<AdminJob[]>(`/admin/jobs?limit=${limit}&offset=${offset}`, { signal, timeoutMs: 15000 }); },
    collectNews(signal?: AbortSignal) { return client.request<Job>('/admin/jobs/collect-news', { method: 'POST', signal, timeoutMs: 15000 }); },
  };
}
export const adminApi = createAdminApi(http);

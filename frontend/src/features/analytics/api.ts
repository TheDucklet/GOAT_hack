import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { Chat, Feed, Insight, Job, Message } from '../../shared/api/types';
export function createAnalyticsApi(client: HttpClient) {
  return {
    feed(companyId: string, limit = 20, offset = 0, signal?: AbortSignal) {
      return client.request<Feed>(`/companies/${encodeURIComponent(companyId)}/feed?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`, { signal });
    },
    buildInsight(companyId: string, eventId: string, signal?: AbortSignal) { return client.request<Insight | Job>(`/companies/${encodeURIComponent(companyId)}/insights`, { method: 'POST', body: { event_id: eventId }, signal }); },
    insight(id: string, signal?: AbortSignal) { return client.request<Insight>(`/insights/${encodeURIComponent(id)}`, { signal }); },
    createChat(companyId: string, eventId: string) { return client.request<Chat>('/chats', { method: 'POST', body: { company_id: companyId, event_id: eventId } }); },
    sendMessage(id: string, text: string) { return client.request<Job>(`/chats/${encodeURIComponent(id)}/messages`, { method: 'POST', body: { text } }); },
    messages(id: string) { return client.request<Message[]>(`/chats/${encodeURIComponent(id)}/messages`); },
  };
}
export const analyticsApi = createAnalyticsApi(http);

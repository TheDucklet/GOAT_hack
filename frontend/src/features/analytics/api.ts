import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { Chat, ChatState, Feed, FeedSnapshot, Insight, Job, Message } from '../../shared/api/types';
export function createAnalyticsApi(client: HttpClient) {
  return {
    feed(companyId: string, limit = 20, offset = 0, signal?: AbortSignal) {
      return client.request<Feed | FeedSnapshot>(`/companies/${encodeURIComponent(companyId)}/feed?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`, { signal });
    },
    buildInsight(companyId: string, eventId: string, signal?: AbortSignal) { return client.request<Insight | Job>(`/companies/${encodeURIComponent(companyId)}/insights`, { method: 'POST', body: { event_id: eventId }, signal }); },
    insight(id: string, signal?: AbortSignal) { return client.request<Insight>(`/insights/${encodeURIComponent(id)}`, { signal }); },
    createChat(companyId: string, eventId: string, signal?: AbortSignal) { return client.request<Chat>('/chats', { method: 'POST', body: { company_id: companyId, event_id: eventId }, signal, timeoutMs: 15000 }); },
    chat(id: string, signal?: AbortSignal) { return client.request<ChatState>(`/chats/${encodeURIComponent(id)}`, { signal, timeoutMs: 15000 }); },
    sendMessage(id: string, text: string, signal?: AbortSignal, clientMessageId?: string, retry = false) { return client.request<Job>(`/chats/${encodeURIComponent(id)}/messages`, { method: 'POST', body: { text, ...(clientMessageId ? { client_message_id: clientMessageId, retry } : {}) }, signal, timeoutMs: 15000 }); },
    messages(id: string, signal?: AbortSignal, limit = 100, offset = 0) { return client.request<Message[]>(`/chats/${encodeURIComponent(id)}/messages?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`, { signal, timeoutMs: 15000 }); },
  };
}
export const analyticsApi = createAnalyticsApi(http);

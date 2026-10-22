import { http } from '../../../shared/api';
import type { HttpClient } from '../../../shared/api/http';
import type { DemoAction, DemoActionRequest, Dismissal, DismissalRequest, Feedback, ProductEvent, ProductEventRequest } from '../../../shared/api/types';

export function createInteractionApi(client: HttpClient) {
  const company = (id: string) => `/companies/${encodeURIComponent(id)}`;
  return {
    dismissals: (id: string, offset: number, signal: AbortSignal) => client.request<Dismissal[]>(`${company(id)}/dismissals?include_details=true&limit=200&offset=${offset}`, { signal, timeoutMs: 15000 }),
    dismiss: (id: string, body: DismissalRequest, signal: AbortSignal) => client.request<Dismissal>(`${company(id)}/dismissals`, { method: 'POST', body, signal, timeoutMs: 15000 }),
    feedback: (id: string, signal: AbortSignal) => client.request<Feedback | null>(`/insights/${encodeURIComponent(id)}/feedback`, { signal, timeoutMs: 15000 }),
    rate: (id: string, rating: -1 | 1, signal: AbortSignal) => client.request<Feedback>('/feedback', { method: 'POST', body: { insight_id: id, rating }, signal, timeoutMs: 15000 }),
    demo: (id: string, body: DemoActionRequest, signal: AbortSignal) => client.request<DemoAction>(`${company(id)}/demo-actions`, { method: 'POST', body, signal, timeoutMs: 15000 }),
    track: (id: string, body: ProductEventRequest, signal: AbortSignal) => client.request<ProductEvent>(`${company(id)}/product-events`, { method: 'POST', body, signal, timeoutMs: 15000 }),
  };
}
export const interactionApi = createInteractionApi(http);

// Stable across reload and a lost response; contains no profile or message text.
export async function demoKey(user: string, company: string, event: string, insight: string) {
  const bytes = new TextEncoder().encode(JSON.stringify(['r09', user, company, event, insight, 'contact_manager']));
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return `r09:${Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

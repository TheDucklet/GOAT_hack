import { http } from './index';
import type { HttpClient } from './http';
import type { Evidence } from './types';

export function createEvidenceApi(client: HttpClient) {
  return {
    source(id: string, signal?: AbortSignal) { return client.request<Evidence>(`/sources/${encodeURIComponent(id)}`, { signal }); },
    fileUrl(id: string, page: number) { return client.url(`/sources/${encodeURIComponent(id)}/file#page=${page}`); },
  };
}
export const evidenceApi = createEvidenceApi(http);

export function externalSourceUrl(value: unknown): URL | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url : null;
  } catch { return null; }
}

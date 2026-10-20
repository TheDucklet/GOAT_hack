import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { AdminStats } from '../../shared/api/types';
export function createAdminApi(client: HttpClient) {
  return { adminStats(signal?: AbortSignal) { return client.request<AdminStats>('/admin/stats', { signal }); } };
}
export const adminApi = createAdminApi(http);

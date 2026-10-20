import { http } from './index';
import type { HttpClient } from './http';
import type { Job } from './types';

// The same job endpoint is shared by analytics and administrative OCR/news flows.
export function createJobsApi(client: HttpClient) {
  return { job(id: string, signal?: AbortSignal) { return client.request<Job>(`/jobs/${encodeURIComponent(id)}`, { signal }); } };
}
export const jobsApi = createJobsApi(http);

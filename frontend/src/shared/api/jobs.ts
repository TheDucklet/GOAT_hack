import { http } from './index';
import type { HttpClient } from './http';
import type { Job } from './types';
import { ApiError, normalizeError } from './errors';

// The same job endpoint is shared by analytics and administrative OCR/news flows.
export function createJobsApi(client: HttpClient) {
  return { job(id: string, signal?: AbortSignal) { return client.request<Job>(`/jobs/${encodeURIComponent(id)}`, { signal, timeoutMs: 15000 }); } };
}
export const jobsApi = createJobsApi(http);

export class JobFailure extends ApiError {
  constructor(public job: Job) {
    super(502, normalizeError(502, job.error || { code: 'job_failed', message: 'Не удалось подготовить результат.' }).body);
  }
}

function pause(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, milliseconds);
    signal.addEventListener('abort', abort, { once: true });
  });
}

// Read-only polling; a network error never resubmits the producer's POST.
export async function waitForJob(initial: Job, signal: AbortSignal, onUpdate: (job: Job) => void, maxWaitMs = 120_000): Promise<Job> {
  let job = initial;
  const deadline = Date.now() + maxWaitMs;
  for (;;) {
    signal.throwIfAborted();
    onUpdate(job);
    if (job.status === 'done') return job;
    if (job.status === 'failed') throw new JobFailure(job);
    if (Date.now() >= deadline) throw normalizeError(408, { code: 'polling_timeout', message: 'Подготовка ещё не завершена. Проверьте статус позже.' });
    await pause(Math.min(2000, deadline - Date.now()), signal);
    job = await jobsApi.job(initial.id, signal);
    if (job.id !== initial.id) throw normalizeError(502, { code: 'invalid_job', message: 'Сервер вернул другое задание.' });
  }
}

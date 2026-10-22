import { afterEach, expect, it, vi } from 'vitest';
import { HttpClient } from './http';
import type { Job } from './types';

vi.mock('./index', () => ({ http: new HttpClient('/api', async () => { throw new Error('Unexpected request'); }) }));
import { jobsApi, waitForJob } from './jobs';

const queued: Job = { id: 'pending', status: 'queued', attempts: 0 };
afterEach(() => { vi.useRealTimers(); });

it('bounds polling without resubmitting a job when no result is ready', async () => {
  vi.useFakeTimers();
  vi.spyOn(jobsApi, 'job').mockResolvedValue(queued);
  const promise = waitForJob(queued, new AbortController().signal, () => {}, 4000);
  const result = expect(promise).rejects.toMatchObject({ body: { code: 'polling_timeout' } });
  await vi.advanceTimersByTimeAsync(4000);
  await result;
  expect(jobsApi.job).toHaveBeenCalledTimes(2);
});

it('cancels the polling timer when its owner unmounts', async () => {
  vi.useFakeTimers();
  vi.spyOn(jobsApi, 'job');
  const controller = new AbortController();
  const promise = waitForJob(queued, controller.signal, () => {});
  const result = expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  controller.abort();
  await result;
  await vi.advanceTimersByTimeAsync(6000);
  expect(jobsApi.job).not.toHaveBeenCalled();
});

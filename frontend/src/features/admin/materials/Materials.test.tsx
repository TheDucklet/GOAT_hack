import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { normalizeError } from '../../../shared/api/errors';
import { jobsApi } from '../../../shared/api/jobs';
import type { AdminNews, BankDocument, Job } from '../../../shared/api/types';
import { adminApi } from '../api';
import { useMaterialJob } from './useMaterialJob';
import { DocumentsPage } from './DocumentsPage';
import { NewsPage } from './NewsPage';
import { JobsPage } from './JobsPage';

const document: BankDocument = { id: 'pdf-1', filename: 'bank.pdf', version: 'v1', document_date: null, page_count: 3, status: 'done', error: null };
const event: AdminNews = { id: 'event-1', title: 'Новость', published_at: null, visible: true, processing_status: 'failed', sources: [{ name: 'Официальный источник', url: 'javascript:alert(1)' }] };
const done: Job = { id: 'job-1', status: 'done', attempts: 1, result: { document_id: document.id, chunks: 3, source_id: 'indexed-source' } };
const queued: Job = { id: done.id, status: 'queued', attempts: 0 };
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((next) => { resolve = next; }); return { promise, resolve }; };
beforeEach(() => {
  vi.spyOn(adminApi, 'documents').mockResolvedValue([document]);
  vi.spyOn(adminApi, 'news').mockResolvedValue([event]);
  vi.spyOn(adminApi, 'jobs').mockResolvedValue([]);
  vi.spyOn(adminApi, 'upload').mockResolvedValue({ document, job: done, source_id: 'placeholder-source' });
  vi.spyOn(adminApi, 'reindex').mockResolvedValue(done);
  vi.spyOn(adminApi, 'retryNews').mockResolvedValue({ ...done, result: { event_id: event.id } });
  vi.spyOn(adminApi, 'collectNews').mockResolvedValue({ ...done, result: {} });
  vi.spyOn(adminApi, 'visibility').mockResolvedValue({ id: event.id, visible: false });
  vi.spyOn(jobsApi, 'job').mockResolvedValue(done);
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute('open'); } });
});
afterEach(() => vi.useRealTimers());

it('uses one accepted job under double clicks and replaces placeholder evidence only after indexing', async () => {
  const refresh = vi.fn(); const deny = vi.fn();
  const { result } = renderHook(() => useMaterialJob(refresh, deny));
  const pending = deferred<{ job: Job; documentId: string; sourceId: string }>();
  const producer = vi.fn().mockReturnValue(pending.promise);
  act(() => { result.current.start('PDF', producer); result.current.start('PDF', producer); });
  expect(producer).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({ job: done, documentId: document.id, sourceId: 'placeholder' }));
  await waitFor(() => expect(result.current.busy).toBe(false));
  expect(result.current.accepted?.sourceId).toBe('indexed-source');
  expect(result.current.success).toContain('завершена');
  expect(deny).not.toHaveBeenCalled();
});

it('resumes only GET after polling fails and never repeats the material POST', async () => {
  vi.useFakeTimers();
  vi.mocked(jobsApi.job).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValue(done);
  const producer = vi.fn().mockResolvedValue({ job: queued, documentId: document.id });
  const { result } = renderHook(() => useMaterialJob(vi.fn(), vi.fn()));
  await act(async () => { result.current.start('PDF', producer); });
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(result.current.canResume).toBe(true);
  await act(async () => { result.current.resume(); });
  expect(result.current.success).toContain('завершена');
  expect(producer).toHaveBeenCalledTimes(1);
  expect(jobsApi.job).toHaveBeenCalledTimes(2);
});

it('does not retry failed work automatically and requires a new explicit material command', async () => {
  const producer = vi.fn().mockResolvedValue({ job: { ...queued, status: 'failed', error: { code: 'invalid_ocr', message: 'OCR не завершён' } } });
  const { result } = renderHook(() => useMaterialJob(vi.fn(), vi.fn()));
  await act(async () => { result.current.start('PDF', producer); });
  expect(result.current.error).toMatchObject({ body: { code: 'invalid_ocr' } });
  expect(result.current.success).toBe(''); expect(result.current.canResume).toBe(false);
  expect(producer).toHaveBeenCalledTimes(1);
});

it.each([401, 403])('clears job/evidence and delegates lost authorization (%s)', async (status) => {
  const deny = vi.fn();
  const { result } = renderHook(() => useMaterialJob(vi.fn(), deny));
  await act(async () => { result.current.start('PDF', async () => { throw normalizeError(status, {}); }); });
  expect(deny).toHaveBeenCalledTimes(1);
  expect(result.current.job).toBeNull(); expect(result.current.accepted).toBeNull();
});

it('ignores a late accepted job after leaving the screen', async () => {
  const pending = deferred<{ job: Job }>(); const refresh = vi.fn();
  const producer = vi.fn().mockReturnValue(pending.promise);
  const view = renderHook(() => useMaterialJob(refresh, vi.fn()));
  act(() => view.result.current.start('PDF', producer));
  const signal = producer.mock.calls[0]![0] as AbortSignal;
  view.unmount(); expect(signal.aborted).toBe(true);
  await act(async () => pending.resolve({ job: done }));
  expect(refresh).not.toHaveBeenCalled();
});

it('does not accept a successful job result for a different document', async () => {
  const { result } = renderHook(() => useMaterialJob(vi.fn(), vi.fn()));
  await act(async () => result.current.start('PDF', async () => ({ job: done, documentId: 'other-pdf' })));
  expect(result.current.error).toMatchObject({ status: 502 }); expect(result.current.success).toBe('');
});

it('rejects oversized or non-PDF selections before HTTP, labels an unknown date, and never auto-uploads', async () => {
  render(<MemoryRouter><DocumentsPage /></MemoryRouter>);
  expect(await screen.findByText('Дата документа: Неизвестна. Страниц: 3.')).toBeVisible();
  const file = new File(['%PDF-'], 'large.pdf', { type: 'application/pdf' });
  Object.defineProperty(file, 'size', { value: 50 * 1024 * 1024 + 1 });
  fireEvent.change(screen.getByLabelText('PDF-файл'), { target: { files: [file] } });
  expect(adminApi.upload).not.toHaveBeenCalled();
  fireEvent.submit(screen.getByRole('form', { name: 'Загрузка PDF' }));
  expect(screen.getByLabelText('PDF-файл')).toHaveAttribute('aria-invalid', 'true');
  expect(adminApi.upload).not.toHaveBeenCalled();
});

it('requires confirmation for global hiding, preserves failure state and rejects unsafe source URLs', async () => {
  render(<MemoryRouter><NewsPage /></MemoryRouter>);
  const row = await screen.findByRole('article', { name: 'Новость: Новость' });
  expect(row.querySelector('a')).toBeNull();
  expect(row).toHaveTextContent('Дата публикации: Неизвестна');
  await userEvent.click(within(row).getByRole('button', { name: 'Скрыть для всех' }));
  expect(adminApi.visibility).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Отмена' }));
  expect(adminApi.visibility).not.toHaveBeenCalled();
  await userEvent.click(within(row).getByRole('button', { name: 'Скрыть для всех' }));
  await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
  expect(await within(row).findByText('Скрыта для всех')).toBeVisible();
  expect(adminApi.visibility).toHaveBeenCalledWith(event.id, false, expect.any(AbortSignal));
  await userEvent.click(within(row).getByRole('button', { name: 'Повторить обработку' }));
  expect(adminApi.retryNews).toHaveBeenCalledTimes(1);
});

it('monitors an existing job without starting new work and limits retries to known material operations', async () => {
  vi.mocked(adminApi.jobs).mockResolvedValue([{ ...queued, kind: 'collect_news' }, { id: 'chat', status: 'failed', kind: 'chat', attempts: 1 }]);
  render(<MemoryRouter><JobsPage /></MemoryRouter>);
  await userEvent.click(await screen.findByRole('button', { name: 'Проверить задание' }));
  expect(await screen.findByText('Обработка завершена. Список обновлён.')).toBeVisible();
  expect(adminApi.collectNews).not.toHaveBeenCalled(); expect(adminApi.reindex).not.toHaveBeenCalled();
  expect(screen.queryAllByRole('button', { name: 'Повторить обработку' })).toHaveLength(0);
});

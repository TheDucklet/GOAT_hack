import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { webcrypto } from 'node:crypto';
import { demoInsight } from '../../../shared/api/mock/fixtures';
import { HttpClient } from '../../../shared/api/http';
import { normalizeError } from '../../../shared/api/errors';
import { AnalyticsSelectionProvider } from '../AnalyticsSelection';
import { createInteractionApi, demoKey, interactionApi } from './api';
import { DEMO_NOTICE, InsightActions } from './InsightActions';
import { useDismissals } from './useDismissals';
import { useInsightTelemetry } from './useInsightTelemetry';
import type { DemoAction, Dismissal, Feedback } from '../../../shared/api/types';

const insight = demoInsight;
const event = { event_id: insight.event_id, title: 'Событие', summary: null, published_at: null, rank_score: 1, status: 'ready', sources: [], relevance_reasons: [] };
const saved: DemoAction = { id: 'demo-1', company_id: insight.company_id, event_id: insight.event_id, insight_id: insight.id, action_type: 'contact_manager', mode: 'demo', status: 'recorded', created_at: '2026-10-23T00:00:00Z' };
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };
beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.removeAttribute('open'); } });
  vi.spyOn(interactionApi, 'feedback').mockResolvedValue(null);
  vi.spyOn(interactionApi, 'track').mockResolvedValue({ id: 'metric', recorded: true, event_type: 'open', excluded_reason: 'test' });
});
function open() { return render(<AnalyticsSelectionProvider companyId={insight.company_id} userId="user" initialEvent={event}><InsightActions insight={insight} /></AnalyticsSelectionProvider>); }

describe('R09 saved card actions', () => {
  it('restores a saved rating, blocks duplicate clicks and allows changing the opinion', async () => {
    vi.mocked(interactionApi.feedback).mockResolvedValue({ id: 'f', rating: 1 });
    const request = deferred<Feedback>();
    const rate = vi.spyOn(interactionApi, 'rate').mockReturnValue(request.promise);
    open();
    const useful = screen.getByRole('button', { name: 'Полезно' });
    await waitFor(() => expect(useful).toHaveAttribute('aria-pressed', 'true'));
    fireEvent.click(useful); expect(rate).not.toHaveBeenCalled();
    const negative = screen.getByRole('button', { name: 'Не полезно' });
    fireEvent.click(negative); fireEvent.click(negative);
    expect(rate).toHaveBeenCalledTimes(1);
    expect(useful).toHaveAttribute('aria-pressed', 'true');
    await act(async () => request.resolve({ id: 'f', rating: -1 }));
    expect(negative).toHaveAttribute('aria-pressed', 'true');
  });

  it('requires confirmation and reuses the same key after a lost response and reload', async () => {
    const demo = vi.spyOn(interactionApi, 'demo').mockRejectedValueOnce(normalizeError(0, {})).mockResolvedValue(saved);
    const view = open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Обсудить с менеджером' })).toBeEnabled());
    expect(screen.getByText(DEMO_NOTICE)).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Обсудить с менеджером' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(demo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Обсудить с менеджером' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    await screen.findByRole('button', { name: 'Повторить изменение' });
    fireEvent.click(screen.getByRole('button', { name: 'Повторить изменение' }));
    await screen.findByText(`Демо-обращение сохранено. ${DEMO_NOTICE}`);
    expect(demo.mock.calls[0]![1]).toEqual(demo.mock.calls[1]![1]);
    view.unmount(); open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Обсудить с менеджером' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Обсудить с менеджером' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    await waitFor(() => expect(demo).toHaveBeenCalledTimes(3));
    expect(demo.mock.calls[2]![1]).toEqual(demo.mock.calls[0]![1]);
    expect(await demoKey('other', insight.company_id, insight.event_id, insight.id)).not.toBe(demo.mock.calls[0]![1].idempotency_key);
  });

  it('does not display success for an action returned from a different context', async () => {
    vi.spyOn(interactionApi, 'demo').mockResolvedValue({ ...saved, company_id: 'other' });
    open();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Обсудить с менеджером' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Обсудить с менеджером' }));
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    await screen.findByRole('alert');
    expect(screen.queryByText(/Демо-обращение сохранено/)).not.toBeInTheDocument();
  });
});

it('restores an exact server version after pagination, and waits for confirmation before refreshing', async () => {
  const row: Dismissal = { event_id: 'e', version: 'old-version', hidden: true, title: '<script>text</script>' };
  vi.spyOn(interactionApi, 'dismissals').mockResolvedValueOnce(Array.from({ length: 200 }, (_, i) => ({ ...row, event_id: `e${i}` }))).mockResolvedValueOnce([row]).mockResolvedValue([]);
  const changed = vi.fn(), denied = vi.fn(), request = deferred<Dismissal>();
  vi.spyOn(interactionApi, 'dismiss').mockReturnValue(request.promise);
  const { result } = renderHook(() => useDismissals('company', changed, denied));
  await waitFor(() => expect(result.current.rows).toHaveLength(201));
  act(() => { void result.current.mutate({ event_id: row.event_id, version: row.version, hidden: false }); });
  expect(changed).not.toHaveBeenCalled();
  act(() => { void result.current.mutate({ event_id: row.event_id, version: row.version, hidden: false }); });
  expect(interactionApi.dismiss).toHaveBeenCalledTimes(1);
  await act(async () => request.resolve({ ...row, hidden: false }));
  expect(changed).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(result.current.rows).toHaveLength(0));
});

it('aborts old company reads and does not expose their late result', async () => {
  const read = deferred<Dismissal[]>();
  const api = vi.spyOn(interactionApi, 'dismissals').mockReturnValueOnce(read.promise).mockResolvedValue([]);
  const { result, rerender } = renderHook(({ company }) => useDismissals(company, vi.fn(), vi.fn()), { initialProps: { company: 'first' } });
  const signal = api.mock.calls[0]![2];
  rerender({ company: 'second' });
  expect(signal.aborted).toBe(true);
  await act(async () => read.resolve([{ event_id: 'private', version: '*', hidden: true }]));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.rows).toEqual([]);
});

it('records an impression only after one continuous visible second and cancels on unmount', async () => {
  vi.useFakeTimers();
  let notify!: IntersectionObserverCallback;
  const disconnect = vi.fn();
  vi.stubGlobal('IntersectionObserver', class { constructor(callback: IntersectionObserverCallback) { notify = callback; } observe() {} disconnect = disconnect; });
  const view = renderHook(() => useInsightTelemetry('c', 'e', 'i'));
  expect(interactionApi.track).toHaveBeenCalledTimes(1);
  act(() => notify([{ isIntersecting: true, intersectionRatio: 0.8 } as IntersectionObserverEntry], {} as IntersectionObserver));
  act(() => vi.advanceTimersByTime(900));
  act(() => notify([{ isIntersecting: false, intersectionRatio: 0 } as IntersectionObserverEntry], {} as IntersectionObserver));
  act(() => vi.advanceTimersByTime(2000));
  expect(interactionApi.track).toHaveBeenCalledTimes(1);
  act(() => notify([{ isIntersecting: true, intersectionRatio: 1 } as IntersectionObserverEntry], {} as IntersectionObserver));
  act(() => vi.advanceTimersByTime(1000));
  expect(interactionApi.track).toHaveBeenLastCalledWith('c', { event_id: 'e', insight_id: 'i', event_type: 'impression' }, expect.any(AbortSignal));
  view.unmount(); expect(disconnect).toHaveBeenCalled();
  expect(vi.mocked(interactionApi.track).mock.calls[0]![2].aborted).toBe(true);
  vi.useRealTimers();
});

it('sends cookie/CSRF with a contextual object payload and no user-controlled identity', async () => {
  const transport = vi.fn(async () => new Response(JSON.stringify(saved), { status: 200 }));
  const client = new HttpClient('/api', transport); client.setCsrfToken('csrf');
  await createInteractionApi(client).demo('company/a', { event_id: 'e', insight_id: 'i', action_type: 'contact_manager', idempotency_key: 'r09:stable' }, new AbortController().signal);
  expect(transport.mock.calls[0]).toBeDefined();
  const [url, init] = (transport.mock.calls as unknown as [string, RequestInit][])[0]!;
  expect(url).toBe('/api/companies/company%2Fa/demo-actions');
  expect(init.credentials).toBe('include');
  expect(new Headers(init.headers).get('X-CSRF-Token')).toBe('csrf');
  expect(JSON.parse(init.body as string)).toEqual({ event_id: 'e', insight_id: 'i', action_type: 'contact_manager', idempotency_key: 'r09:stable' });
});

import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpClient } from '../../shared/api/http';
import { createMockTransport } from '../../shared/api/mock/transport';
import { demoMe, demoMembership } from '../../shared/api/mock/fixtures';
import { normalizeError } from '../../shared/api/errors';
import { insightNotice } from '../../shared/api/insight-contract';
import type { Feed, FeedItem } from '../../shared/api/types';

vi.mock('../../shared/api/index', () => ({ http: new HttpClient('/api', createMockTransport()) }));
import { authApi } from '../auth/api';
import { companiesApi } from '../companies/api';
import { analyticsApi } from './api';
import { interactionApi } from './interactions/api';
import { App } from '../../app/App';
import { AnalyticsSelectionProvider, useAnalyticsSelection } from './AnalyticsSelection';

const companies = [{ id: 'company-a', name: 'Компания A', profile_version: 'v1' }, { id: 'company-b', name: 'Компания B', profile_version: 'v2' }];
function event(id = 'event-1'): FeedItem {
  return { event_id: id, title: `Событие ${id}`, summary: 'Изменились условия расчётов.',
    published_at: '2026-10-21T09:00:00Z', rank_score: 4, status: 'ready',
    sources: [{ id: 'source-1', url: 'https://example.org/news/1' }],
    relevance_reasons: [{ factor: 'industry', event_topic: '25.61', feature_path: 'features.MAINOKVED_CODE' }] };
}
function page(items: FeedItem[] = [event()], total = items.length, offset = 0): Feed {
  return { items, total, offset, limit: 20 };
}
function open(path = '/app/analytics') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.spyOn(interactionApi, 'dismissals').mockResolvedValue([]);
  vi.spyOn(authApi, 'me').mockResolvedValue({ ...structuredClone(demoMe), memberships: companies.map((company) => ({ ...demoMembership, id: `m-${company.id}`, company_id: company.id })) });
  vi.spyOn(companiesApi, 'companies').mockResolvedValue(companies);
  vi.spyOn(analyticsApi, 'feed').mockResolvedValue(page());
});

describe('R-04 personalized feed', () => {
  it('keeps a permanent analytics link on the main screen and displays API fields', async () => {
    open('/app');
    await userEvent.click(await screen.findByRole('link', { name: /Открыть бизнес-аналитику/ }));
    expect(await screen.findByRole('button', { name: 'Событие event-1' })).toBeVisible();
    for (const note of screen.getAllByRole('note')) expect(note).toHaveTextContent(insightNotice.disclaimer);
    expect(analyticsApi.feed).toHaveBeenCalledWith('company-a', 20, 0, expect.any(AbortSignal));
    expect(screen.getByText('Изменились условия расчётов.')).toBeVisible();
    expect(screen.getByText('Отрасль: 25.61')).toBeVisible();
    expect(screen.getByRole('link', { name: /example.org/ })).toHaveAttribute('href', 'https://example.org/news/1');
    expect(document.querySelector('time')).toHaveAttribute('datetime', '2026-10-21T09:00:00Z');
    expect(document.querySelector('time')).toHaveTextContent('12:00 МСК');
  });

  it('shows loading, then the specified empty state', async () => {
    const result = deferred<Feed>();
    vi.mocked(analyticsApi.feed).mockReturnValue(result.promise);
    open();
    expect(await screen.findByText('Загружаем события…')).toBeVisible();
    expect(screen.queryByText('Нет подходящих событий')).not.toBeInTheDocument();
    await act(async () => result.resolve(page([])));
    expect(await screen.findByText('Нет подходящих событий')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Загрузить ещё' })).not.toBeInTheDocument();
  });

  it('opens a ready snapshot card by saved id without requesting new generation', async () => {
    vi.mocked(analyticsApi.feed).mockResolvedValue({ ...page(), schema_version: 'v2', snapshot_id: 'snapshot', generation_status: 'ready', versions: {}, stale: false, stale_reasons: [], ranking_version: 'test', ranking_as_of: '2026-10-23T00:00:00Z', ready_at: null, job_id: null, error: null, next_offset: null,
      items: [{ ...event(), generation_status: 'ready', insight_id: 'saved-card', impact_level: 'low', relevance_status: 'active', versions: {} }] });
    const read = vi.spyOn(analyticsApi, 'insight').mockReturnValue(new Promise(() => {}));
    const build = vi.spyOn(analyticsApi, 'buildInsight');
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Событие event-1' }));
    expect(read).toHaveBeenCalledWith('saved-card', expect.any(AbortSignal));
    expect(build).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Загрузить ещё' })).not.toBeInTheDocument();
  });

  it('appends pages in server order and prevents repeated loading while pending', async () => {
    const next = deferred<Feed>();
    vi.mocked(analyticsApi.feed).mockResolvedValueOnce(page(Array.from({ length: 20 }, (_, i) => event(`e-${i}`)), 21)).mockReturnValueOnce(next.promise);
    open();
    const more = await screen.findByRole('button', { name: 'Загрузить ещё' });
    await userEvent.click(more); fireEvent.click(more);
    expect(more).toBeDisabled();
    expect(analyticsApi.feed).toHaveBeenCalledTimes(2);
    expect(analyticsApi.feed).toHaveBeenLastCalledWith('company-a', 20, 20, expect.any(AbortSignal));
    await act(async () => next.resolve(page([event('last')], 21, 20)));
    expect(await screen.findByText('Показано 21 из 21')).toBeVisible();
    expect(within(screen.getByRole('list', { name: 'События' })).getAllByRole('article')).toHaveLength(21);
    expect(screen.queryByRole('button', { name: 'Загрузить ещё' })).not.toBeInTheDocument();
  });

  it('preserves loaded events after a next-page outage and retries the same offset without duplicates', async () => {
    vi.mocked(analyticsApi.feed).mockResolvedValueOnce(page([event()], 3))
      .mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValueOnce(page([event(), event('second')], 3, 1));
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Загрузить ещё' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    expect(screen.getByRole('button', { name: 'Событие event-1' })).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: 'Событие second' })).toBeVisible();
    expect(screen.getAllByRole('button', { name: 'Событие event-1' })).toHaveLength(1);
    expect(analyticsApi.feed).toHaveBeenLastCalledWith('company-a', 20, 1, expect.any(AbortSignal));
  });

  it('retries a failed first page', async () => {
    vi.mocked(analyticsApi.feed).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValueOnce(page());
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: 'Событие event-1' })).toBeVisible();
  });

  it('sends the same selected event id to the insight and chat panels', async () => {
    open();
    const button = await screen.findByRole('button', { name: 'Событие event-1' });
    await userEvent.click(button);
    expect(button).toHaveAttribute('aria-pressed', 'true');
    for (const name of ['Анализ события', 'Диалог по событию']) {
      const panel = screen.getByRole('region', { name });
      expect(panel).toHaveAttribute('data-event-id', 'event-1');
      expect(within(panel).getByRole('heading', { name: 'Событие event-1' })).toBeVisible();
    }
  });

  it('clears selected panels and previous pages on company change and ignores late responses', async () => {
    const late = deferred<Feed>();
    vi.mocked(analyticsApi.feed).mockResolvedValueOnce(page([event()], 2))
      .mockReturnValueOnce(late.promise).mockResolvedValueOnce(page([event('company-b-event')]));
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Событие event-1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }));
    const signal = vi.mocked(analyticsApi.feed).mock.calls[1]![3]!;
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Компания' }), 'company-b');
    expect(await screen.findByRole('button', { name: 'Событие company-b-event' })).toBeVisible();
    expect(signal.aborted).toBe(true);
    await act(async () => late.resolve(page([event('old-late-event')], 2, 1)));
    expect(screen.queryByRole('button', { name: 'Событие old-late-event' })).not.toBeInTheDocument();
    expect(screen.queryByText('Событие event-1')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Анализ события' })).not.toHaveAttribute('data-event-id');
    expect(analyticsApi.feed).toHaveBeenLastCalledWith('company-b', 20, 0, expect.any(AbortSignal));
  });

  it('refreshes from the first page and displays changed server news', async () => {
    vi.mocked(analyticsApi.feed).mockResolvedValueOnce(page()).mockResolvedValueOnce(page([{ ...event(), title: 'Обновлённая новость' }]));
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Событие event-1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Обновить ленту' }));
    expect(await screen.findByRole('button', { name: 'Обновлённая новость' })).toBeVisible();
    expect(screen.queryByText('Событие event-1')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Диалог по событию' })).not.toHaveAttribute('data-event-id');
  });

  it('removes loaded company data and selection when access is revoked', async () => {
    vi.mocked(analyticsApi.feed).mockResolvedValueOnce(page([event()], 2)).mockRejectedValueOnce(normalizeError(403, {}))
      .mockResolvedValueOnce(page([event('restored')]));
    open();
    await userEvent.click(await screen.findByRole('button', { name: 'Событие event-1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Загрузить ещё' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    await waitFor(() => expect(screen.queryByText('Событие event-1')).not.toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('button', { name: 'Событие restored' })).toBeVisible();
    expect(analyticsApi.feed).toHaveBeenLastCalledWith('company-a', 20, 0, expect.any(AbortSignal));
  });

  it('renders missing metadata and rejects executable source URLs without interpreting news HTML', async () => {
    vi.mocked(analyticsApi.feed).mockResolvedValue(page([{ ...event(), title: '<img src=x onerror=alert(1)>',
      summary: null, published_at: null, relevance_reasons: [], sources: [{ url: 'javascript:alert(1)' }] }]));
    open();
    expect(await screen.findByRole('button', { name: '<img src=x onerror=alert(1)>' })).toBeVisible();
    expect(screen.getByText('Дата не указана')).toBeVisible();
    expect(screen.getByText('Краткое описание пока отсутствует.')).toBeVisible();
    expect(screen.getByText('Персональные причины не указаны')).toBeVisible();
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(document.querySelector('.feed-event img')).toBeNull();
  });

  it('clears an existing chat when event or company changes and rejects a foreign chat context', async () => {
    function Consumer() {
      const state = useAnalyticsSelection();
      return <><output data-testid="selection">{state.companyId}/{state.event?.event_id}/{state.chat?.id}</output>
        <button onClick={() => state.selectEvent(event())}>Select</button>
        <button onClick={() => state.selectEvent(event('new'))}>Another</button>
        <button onClick={() => state.setChat({ id: 'chat', company_id: state.companyId, event_id: state.event!.event_id })}>Chat</button>
        <button onClick={() => state.setChat({ id: 'foreign', company_id: 'foreign', event_id: 'event-1' })}>Foreign</button></>;
    }
    const view = render(<AnalyticsSelectionProvider companyId="a"><Consumer /></AnalyticsSelectionProvider>);
    await userEvent.click(screen.getByText('Select')); await userEvent.click(screen.getByText('Chat'));
    expect(screen.getByTestId('selection')).toHaveTextContent('a/event-1/chat');
    await userEvent.click(screen.getByText('Foreign'));
    expect(screen.getByTestId('selection')).not.toHaveTextContent('foreign');
    await userEvent.click(screen.getByText('Another'));
    expect(screen.getByTestId('selection')).toHaveTextContent('a/new/');
    await userEvent.click(screen.getByText('Chat'));
    view.rerender(<AnalyticsSelectionProvider companyId="b"><Consumer /></AnalyticsSelectionProvider>);
    expect(screen.getByTestId('selection')).toHaveTextContent('b//');
  });
});

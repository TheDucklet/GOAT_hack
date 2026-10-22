import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import examples from '../../../../../docs/contracts/insight-v2-examples.json';
import { HttpClient } from '../../../shared/api/http';
import { normalizeError } from '../../../shared/api/errors';
import { insightNotice } from '../../../shared/api/insight-contract';
import { jobsApi } from '../../../shared/api/jobs';
import type { FeedItem, Insight, InsightResultV2, Job } from '../../../shared/api/types';

vi.mock('../../../shared/api/index', () => ({ http: new HttpClient('/api', async () => { throw new Error('Unexpected HTTP request'); }) }));
import { analyticsApi } from '../api';
import { AnalyticsSelectionProvider, useAnalyticsSelection } from '../AnalyticsSelection';
import { InsightPanel } from './InsightPanel';
import { InsightContent } from './InsightContent';

function card(name = 'historical_bank_position'): Insight {
  const example = examples.find((item) => item.name === name)!;
  return { id: 'insight-a', company_id: 'company-a', event_id: 'event-a', versions: {}, stale: false, stale_reasons: [], result: structuredClone(example.envelope.result) as InsightResultV2 };
}
const queued: Job = { id: 'job-a', status: 'queued', result: null, error: null, attempts: 0 };
const done: Job = { ...queued, status: 'done', result: { insight_id: 'insight-a' } };
const event = (id = 'event-a'): FeedItem => ({ event_id: id, title: id, summary: null, published_at: null, sources: [], relevance_reasons: [], status: 'done', rank_score: 1 });
function Controls() {
  const state = useAnalyticsSelection();
  return <><button onClick={() => state.selectEvent(event())}>Select</button>
    <button onClick={() => state.selectEvent(event('event-b'))}>Another</button>
    <button onClick={() => state.selectEvent(event(), 'insight-a')}>Saved</button>
    <output data-testid="insight-id">{state.insightId}</output><InsightPanel /></>;
}
function open(companyId = 'company-a') { return render(<AnalyticsSelectionProvider companyId={companyId}><Controls /></AnalyticsSelectionProvider>); }
function notice() { expect(screen.getByRole('note')).toHaveTextContent(insightNotice.disclaimer); }
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
beforeEach(() => {
  vi.spyOn(analyticsApi, 'buildInsight').mockResolvedValue(card());
  vi.spyOn(analyticsApi, 'insight').mockResolvedValue(card());
  vi.spyOn(jobsApi, 'job').mockResolvedValue(done);
});
afterEach(() => { vi.useRealTimers(); });

describe('R-05 grounded insight panel', () => {
  it('uses an explicit generation action, keeps the policy visible and renders dated historical material', async () => {
    open(); notice();
    fireEvent.click(screen.getByText('Select'));
    expect(analyticsApi.buildInsight).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Подготовить анализ' }));
    expect(await screen.findByText(/Исторический банковский материал/)).toBeVisible();
    expect(screen.getByText('2024-06-01')).toBeVisible();
    expect(screen.getByTestId('insight-id')).toHaveTextContent('insight-a');
    expect(analyticsApi.buildInsight).toHaveBeenCalledExactlyOnceWith('company-a', 'event-a', expect.any(AbortSignal));
    expect(analyticsApi.insight).not.toHaveBeenCalled();
    expect(jobsApi.job).not.toHaveBeenCalled(); notice();
  });

  it('reads a supplied saved insight id without a generation POST', async () => {
    open(); fireEvent.click(screen.getByText('Saved'));
    expect(await screen.findByText(/Исторический банковский материал/)).toBeVisible();
    expect(analyticsApi.insight).toHaveBeenCalledExactlyOnceWith('insight-a', expect.any(AbortSignal));
    expect(analyticsApi.buildInsight).not.toHaveBeenCalled();
  });

  it('polls the queued job after two seconds, reads its result and never resubmits generation on render', async () => {
    vi.useFakeTimers();
    vi.mocked(analyticsApi.buildInsight).mockResolvedValue(queued);
    const view = open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    await act(async () => {});
    expect(screen.getByText('Анализ в очереди…')).toBeVisible(); notice();
    await act(async () => { await vi.advanceTimersByTimeAsync(1999); });
    expect(jobsApi.job).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(analyticsApi.insight).toHaveBeenCalledExactlyOnceWith('insight-a', expect.any(AbortSignal));
    view.rerender(<AnalyticsSelectionProvider companyId="company-a"><Controls /></AnalyticsSelectionProvider>);
    expect(analyticsApi.buildInsight).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Исторический банковский материал/)).toBeVisible();
  });

  it('resumes GET polling after an outage instead of repeating the accepted POST', async () => {
    vi.useFakeTimers();
    vi.mocked(analyticsApi.buildInsight).mockResolvedValue(queued);
    vi.mocked(jobsApi.job).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValue(done);
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole('alert')).toBeVisible(); notice();
    fireEvent.click(screen.getByText('Повторить'));
    await act(async () => {});
    expect(screen.getByText(/Исторический банковский материал/)).toBeVisible();
    expect(analyticsApi.buildInsight).toHaveBeenCalledTimes(1);
    expect(jobsApi.job).toHaveBeenCalledTimes(2);
  });

  it('shows budget failure honestly and allows only a manual new attempt', async () => {
    vi.mocked(analyticsApi.buildInsight).mockResolvedValueOnce({ ...queued, status: 'failed', error: { code: 'budget_exhausted', message: 'Budget limit' } }).mockResolvedValue(card());
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    expect(await screen.findByText(/Дневной бюджет ИИ исчерпан/)).toBeVisible(); notice();
    expect(screen.queryByText(/Исторический банковский материал/)).not.toBeInTheDocument();
    expect(analyticsApi.buildInsight).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Повторить'));
    expect(await screen.findByText(/Исторический банковский материал/)).toBeVisible();
    expect(analyticsApi.buildInsight).toHaveBeenCalledTimes(2);
  });

  it('aborts a pending request on company switch and discards a late successful result', async () => {
    const late = deferred<Insight>();
    vi.mocked(analyticsApi.buildInsight).mockReturnValue(late.promise);
    const view = open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    const signal = vi.mocked(analyticsApi.buildInsight).mock.calls[0]![2]!;
    view.rerender(<AnalyticsSelectionProvider companyId="company-b"><Controls /></AnalyticsSelectionProvider>);
    expect(signal.aborted).toBe(true);
    await act(async () => late.resolve(card()));
    expect(screen.queryByText(/Исторический банковский материал/)).not.toBeInTheDocument(); notice();
  });

  it('stops polling when the selected event changes', async () => {
    vi.useFakeTimers(); vi.mocked(analyticsApi.buildInsight).mockResolvedValue(queued);
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    await act(async () => {});
    fireEvent.click(screen.getByText('Another'));
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(jobsApi.job).not.toHaveBeenCalled();
    expect(screen.getByRole('region', { name: 'Анализ события' })).toHaveAttribute('data-event-id', 'event-b');
  });

  it('rejects a foreign response even if a server incorrectly returns 200', async () => {
    vi.mocked(analyticsApi.buildInsight).mockResolvedValue({ ...card(), company_id: 'foreign' });
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Карточка не относится');
    expect(screen.queryByText(/Исторический банковский материал/)).not.toBeInTheDocument(); notice();
  });

  it('clears the card after an access revocation and keeps the policy on errors', async () => {
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    await screen.findByText(/Исторический банковский материал/);
    vi.mocked(analyticsApi.insight).mockRejectedValue(normalizeError(403, {}));
    fireEvent.click(screen.getByText('Проверить актуальность'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByText(/Исторический банковский материал/)).not.toBeInTheDocument(); notice();
    expect(screen.queryByText('Повторить')).not.toBeInTheDocument();
  });

  it('renders undetermined impact as insufficient data while the external interpretation remains available', async () => {
    vi.mocked(analyticsApi.buildInsight).mockResolvedValue(card('unknown_strength'));
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    expect(await screen.findByRole('heading', { name: 'Влияние: Недостаточно данных' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: 'Влияние: Низкое' })).not.toBeInTheDocument();
    expect(screen.getByText('Позиция банка отсутствует')).toBeVisible();
    expect(screen.getByRole('region', { name: 'Интерпретация ИИ' })).toBeVisible(); notice();
  });

  it('renders a partial legacy result without losing the application disclaimer', async () => {
    vi.mocked(analyticsApi.buildInsight).mockResolvedValue({ ...card(), result: { facts: [], unknowns: [] } as unknown as Insight['result'] });
    open(); fireEvent.click(screen.getByText('Select')); fireEvent.click(screen.getByText('Подготовить анализ'));
    expect(await screen.findByText(/Карточка v1/)).toBeVisible();
    expect(screen.getByText('Позиция банка отсутствует')).toBeVisible(); notice();
  });

  it('marks stale cards, assumptions, hypotheses and scenarios without evaluating generated formulas or HTML', async () => {
    const value = card('quantitative_scenario_synthetic');
    value.stale = true;
    const result = value.result as InsightResultV2;
    const scenario = result.risks.find((item) => item.quantitative_scenario)!;
    scenario.quantitative_scenario!.formula = 'window.alert("must not run")';
    scenario.text = '<script>alert(1)</script>';
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => {});
    render(<InsightContent insight={value} />);
    expect(screen.getByText(/Карточка устарела/)).toBeVisible();
    expect(screen.getAllByText('Сценарий').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Гипотеза').length).toBeGreaterThan(0);
    expect(screen.getByText('<script>alert(1)</script>')).toBeVisible();
    expect(screen.getByText('window.alert("must not run")')).toBeVisible();
    expect(document.querySelector('script')).toBeNull(); expect(alert).not.toHaveBeenCalled();
  });
});

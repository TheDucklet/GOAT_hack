import { useEffect, useRef, useState } from 'react';
import type { Insight } from '../../../shared/api/types';
import { ApiError } from '../../../shared/api/errors';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { ErrorNotice } from '../../../shared/ui/ErrorNotice';
import { useAnalyticsSelection } from '../AnalyticsSelection';
import { demoKey, interactionApi } from './api';
import { useInsightTelemetry } from './useInsightTelemetry';

export const DEMO_NOTICE = 'Демонстрация — запрос в банк не отправлен';
export function InsightActions({ insight, hide }: { insight: Insight; hide?: () => void }) {
  const { userId, companyId, event, selectEvent } = useAnalyticsSelection();
  const [rating, setRating] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [recorded, setRecorded] = useState(false);
  const [demoError, setDemoError] = useState<unknown>(null);
  const pending = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const marker = useInsightTelemetry(companyId, insight.event_id, insight.id);
  useEffect(() => {
    const request = new AbortController(); controller.current = request;
    setLoading(true); setError(null);
    void interactionApi.feedback(insight.id, request.signal).then((value) => {
      if (!request.signal.aborted) setRating(value?.rating ?? null);
    }).catch((reason: unknown) => {
      if (!request.signal.aborted) {
        setError(reason);
        if (reason instanceof ApiError && [401, 403].includes(reason.status)) selectEvent(null);
      }
    })
      .finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [insight.id, attempt, selectEvent]);
  function fail(reason: unknown, demo = false) {
    (demo ? setDemoError : setError)(reason);
    if (reason instanceof ApiError && [401, 403].includes(reason.status)) selectEvent(null);
  }
  async function rate(next: -1 | 1) {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted || pending.current || loading || rating === next) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const saved = await interactionApi.rate(insight.id, next, signal);
      if (!signal.aborted) {
        if (saved.rating !== next) throw new Error('Оценка не подтверждена сервером');
        setRating(saved.rating);
      }
    } catch (reason) { if (!signal.aborted) fail(reason); }
    finally { pending.current = false; if (!signal.aborted) setBusy(false); }
  }
  async function confirm() {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted || pending.current || recorded) return;
    pending.current = true; setBusy(true); setDemoError(null);
    try {
      const idempotency_key = await demoKey(userId, companyId, insight.event_id, insight.id);
      if (signal.aborted) return;
      const saved = await interactionApi.demo(companyId, { event_id: insight.event_id, insight_id: insight.id, action_type: 'contact_manager', idempotency_key }, signal);
      if (signal.aborted) return;
      if (saved.company_id !== companyId || saved.event_id !== insight.event_id || saved.insight_id !== insight.id || saved.mode !== 'demo' || saved.status !== 'recorded' || saved.action_type !== 'contact_manager') throw new Error('Действие не подтверждено сервером');
      setRecorded(true); setConfirming(false);
    } catch (reason) { if (!signal.aborted) fail(reason, true); }
    finally { pending.current = false; if (!signal.aborted) setBusy(false); }
  }
  return <section className="insight-actions" aria-label="Действия с анализом">
    <div ref={marker}><h4>Ваша оценка анализа</h4><p className="muted">Оценка и скрытие относятся только к вашему профилю.</p></div>
    {loading && <p role="status">Загружаем вашу оценку…</p>}
    {error != null && <ErrorNotice error={error} retry={() => setAttempt((value) => value + 1)} />}
    <div className="interaction-buttons">
      <button className="button secondary" aria-pressed={rating === 1} disabled={loading || busy || confirming} onClick={() => void rate(1)}>Полезно</button>
      <button className="button secondary" aria-pressed={rating === -1} disabled={loading || busy || confirming} onClick={() => void rate(-1)}>Не полезно</button>
      {hide && <button className="button secondary" disabled={busy || confirming} onClick={hide}>Скрыть</button>}
    </div>
    <p className="demo-notice">{DEMO_NOTICE}</p>
    {recorded && <p role="status">Демо-обращение сохранено. {DEMO_NOTICE}</p>}
    <button className="button secondary" disabled={busy || recorded || loading} onClick={() => { setDemoError(null); setConfirming(true); }}>Обсудить с менеджером</button>
    {confirming && <ConfirmDialog title="Сохранить демо-обращение?" description={`${event?.title}. Компания: ${companyId}. ${DEMO_NOTICE}`} busy={busy} error={demoError} confirm={() => void confirm()} cancel={() => setConfirming(false)} />}
  </section>;
}

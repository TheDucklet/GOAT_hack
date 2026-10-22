import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, normalizeError } from '../../../shared/api/errors';
import { JobFailure, jobsApi, waitForJob } from '../../../shared/api/jobs';
import type { Insight, Job } from '../../../shared/api/types';
import { analyticsApi } from '../api';

function checkInsight(insight: Insight, companyId: string, eventId: string) {
  if (!insight || typeof insight.id !== 'string' || insight.company_id !== companyId || insight.event_id !== eventId) {
    throw normalizeError(502, { code: 'wrong_insight_context', message: 'Карточка не относится к выбранной компании и событию.' });
  }
  const result = insight.result;
  if (!result || typeof result !== 'object' || Array.isArray(result) || ('schema_version' in result && result.schema_version !== 'v2')) {
    throw normalizeError(502, { code: 'unsupported_insight', message: 'Формат карточки не поддерживается. Обновите приложение.' });
  }
  return insight;
}

export function useInsight(companyId: string, eventId: string, savedId: string | null, onReady: (insight: Insight) => void) {
  const [insight, setInsight] = useState<Insight | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const controller = useRef<AbortController | null>(null);
  const pendingJob = useRef<Job | null>(null);
  const resolvedId = useRef<string | null>(savedId);
  const loadedId = useRef<string | null>(null);

  const load = useCallback((mode: 'build' | 'read' | 'resume') => {
    if (controller.current && !controller.current.signal.aborted) return;
    const request = new AbortController();
    controller.current = request;
    const signal = request.signal;
    setLoading(true); setError(null); setInsight(null);
    void (async () => {
      let value: Insight;
      if (mode === 'build') {
        pendingJob.current = null; resolvedId.current = null; setJob(null);
        const response = await analyticsApi.buildInsight(companyId, eventId, signal);
        signal.throwIfAborted();
        if ('status' in response) {
          pendingJob.current = response;
        } else {
          return checkInsight(response, companyId, eventId);
        }
      }
      if (pendingJob.current) {
        const initial = mode === 'resume' ? await jobsApi.job(pendingJob.current.id, signal) : pendingJob.current;
        const finished = await waitForJob(initial, signal, (next) => {
          if (!signal.aborted) { pendingJob.current = next; setJob(next); }
        });
        const id = finished.result?.insight_id;
        if (typeof id !== 'string' || !id) throw normalizeError(502, { code: 'invalid_job_result', message: 'Задание завершено без идентификатора карточки.' });
        resolvedId.current = id; pendingJob.current = null;
      }
      if (!resolvedId.current) throw normalizeError(502, { message: 'Идентификатор карточки не указан.' });
      value = await analyticsApi.insight(resolvedId.current, signal);
      return checkInsight(value, companyId, eventId);
    })().then((value) => {
      if (signal.aborted) return;
      resolvedId.current = value.id; loadedId.current = value.id;
      setInsight(value); onReady(value);
    }).catch((reason: unknown) => {
      if (signal.aborted) return;
      if (reason instanceof JobFailure) pendingJob.current = null;
      setError(reason);
    }).finally(() => {
      if (!signal.aborted) { setLoading(false); controller.current = null; }
    });
  }, [companyId, eventId, onReady]);

  useEffect(() => {
    if (savedId && loadedId.current !== savedId) {
      controller.current?.abort();
      resolvedId.current = savedId;
      load('read');
    }
  }, [savedId, load]);
  useEffect(() => () => { controller.current?.abort(); }, []);

  return {
    insight, job, loading, error,
    forbidden: error instanceof ApiError && error.status === 403,
    build: () => load('build'),
    refresh: () => load('read'),
    retry: () => load(pendingJob.current ? 'resume' : resolvedId.current ? 'read' : 'build'),
  };
}

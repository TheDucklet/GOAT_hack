import { useEffect, useRef, useState } from 'react';
import { ApiError, normalizeError } from '../../../shared/api/errors';
import { JobFailure, jobsApi, waitForJob } from '../../../shared/api/jobs';
import type { Job } from '../../../shared/api/types';

export interface AcceptedMaterial { job: Job | null; sourceId?: string | null; documentId?: string }

// Only explicit commands POST. A retry of accepted work reads its job, never restarts it.
export function useMaterialJob(refresh: () => void, deny: (error: unknown) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [accepted, setAccepted] = useState<AcceptedMaterial | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState('');
  const [label, setLabel] = useState('');
  const [canResume, setCanResume] = useState(false);
  const active = useRef<AbortController | null>(null);
  const pending = useRef<Job | null>(null);
  const material = useRef<AcceptedMaterial | null>(null);
  useEffect(() => () => active.current?.abort(), []);

  const run = (name: string, producer?: (signal: AbortSignal) => Promise<AcceptedMaterial>, existing?: Job) => {
    if (active.current && !active.current.signal.aborted) return;
    const controller = new AbortController(); active.current = controller;
    const signal = controller.signal;
    setBusy(true); setError(null); setSuccess(''); setCanResume(false); setLabel(name);
    if (producer) { pending.current = null; setJob(null); setAccepted(null); }
    void (async () => {
      if (producer) {
        const outcome = await producer(signal);
        signal.throwIfAborted(); setAccepted(outcome); material.current = outcome; pending.current = outcome.job;
        refresh();
        if (!outcome.job) { setSuccess('Документ уже обработан. Новое задание не создавалось.'); return; }
      } else {
        const id = (existing || pending.current)?.id;
        if (!id) return;
        pending.current = await jobsApi.job(id, signal);
        if (pending.current.id !== id) throw normalizeError(502, { message: 'Получено другое задание.' });
      }
      if (!pending.current) return;
      const completed = await waitForJob(pending.current, signal, (next) => {
        if (!signal.aborted) { pending.current = next; setJob(next); }
      });
      signal.throwIfAborted();
      if (material.current?.documentId && completed.result?.document_id !== material.current.documentId) throw normalizeError(502, { message: 'Задание завершено для другого документа.' });
      if (material.current && typeof completed.result?.source_id === 'string') {
        material.current = { ...material.current, sourceId: completed.result.source_id }; setAccepted(material.current);
      }
      setJob(completed); setSuccess('Обработка завершена. Список обновлён.'); refresh();
    })().catch((reason: unknown) => {
      if (signal.aborted) return;
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) { pending.current = null; setJob(null); setAccepted(null); deny(reason); }
      else { setCanResume(!!pending.current && !(reason instanceof JobFailure)); if (reason instanceof JobFailure) refresh(); }
      setError(reason);
    }).finally(() => { if (!signal.aborted) { active.current = null; setBusy(false); } });
  };
  return { job, accepted, busy, error, success, label, canResume,
    start: run,
    monitor(existing: Job) { material.current = null; setAccepted(null); pending.current = existing; run('Проверка задания', undefined, existing); },
    resume() { run(label); },
  };
}

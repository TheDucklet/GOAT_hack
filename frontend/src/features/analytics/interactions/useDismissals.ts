import { useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../shared/api/errors';
import type { Dismissal, DismissalRequest } from '../../../shared/api/types';
import { interactionApi } from './api';

export function useDismissals(companyId: string, changed: () => void, denied: () => void) {
  const [rows, setRows] = useState<Dismissal[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const callbacks = useRef({ changed, denied });
  callbacks.current = { changed, denied };
  const pending = useRef(false);
  useEffect(() => {
    const request = new AbortController(); controller.current = request;
    setLoading(true); setError(null);
    void (async () => {
      const all: Dismissal[] = [];
      for (let offset = 0; ; offset += 200) {
        const page = await interactionApi.dismissals(companyId, offset, request.signal);
        all.push(...page);
        if (page.length < 200) break;
      }
      if (!request.signal.aborted) setRows(all);
    })().catch((reason: unknown) => {
      if (request.signal.aborted) return;
      setError(reason);
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) { setRows([]); callbacks.current.denied(); }
    }).finally(() => { if (!request.signal.aborted) setLoading(false); });
    return () => request.abort();
  }, [companyId, attempt]);

  async function mutate(body: DismissalRequest) {
    const signal = controller.current?.signal;
    if (!signal || signal.aborted || pending.current || loading) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const row = await interactionApi.dismiss(companyId, body, signal);
      if (signal.aborted) return;
      if (row.event_id !== body.event_id || row.hidden !== body.hidden) throw new Error('Сервер вернул другое событие');
      callbacks.current.changed();
      setAttempt((value) => value + 1);
    } catch (reason) {
      if (!signal.aborted) {
        setError(reason);
        if (reason instanceof ApiError && [401, 403].includes(reason.status)) { setRows([]); callbacks.current.denied(); }
      }
    } finally { pending.current = false; if (!signal.aborted) setBusy(false); }
  }
  return { rows, loading, busy, error, mutate, retry: () => setAttempt((value) => value + 1) };
}

import { useEffect, useRef, useState } from 'react';
import { ApiError, normalizeError } from '../../../shared/api/errors';

export interface AdminAction<T> {
  title: string;
  description: string;
  success: string;
  id: string;
  validate(row: T): boolean;
  save(signal: AbortSignal): Promise<T>;
}

export function useAdminAction<T extends { id: string }>(replace: (row: T) => void, deny: (reason: unknown) => void) {
  const [action, setAction] = useState<AdminAction<T> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState('');
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  return {
    action, busy, error, success,
    prepare(next: AdminAction<T>) { if (!active.current) { setAction(next); setError(null); setSuccess(''); } },
    cancel() { if (!active.current) { setAction(null); setError(null); } },
    async confirm() {
      if (!action || active.current) return;
      const controller = new AbortController(); active.current = controller;
      setBusy(true); setError(null); setSuccess('');
      try {
        const row = await action.save(controller.signal);
        if (controller.signal.aborted) return;
        if (row.id !== action.id || !action.validate(row)) throw normalizeError(502, { message: 'Сервер не подтвердил ожидаемое изменение. Обновите список.' });
        replace(row); setSuccess(action.success); setAction(null);
      } catch (reason) {
        if (controller.signal.aborted) return;
        if (reason instanceof ApiError && [401, 403].includes(reason.status)) { setAction(null); deny(reason); }
        else setError(reason);
      } finally { if (!controller.signal.aborted) { active.current = null; setBusy(false); } }
    },
  };
}

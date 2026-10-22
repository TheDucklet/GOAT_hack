import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { normalizeError } from '../../../shared/api/errors';
import type { Chat, ChatState, Company } from '../../../shared/api/types';
import { analyticsApi } from '../api';

// Only a chat identifier is persisted in the URL. Context comes from an authorized server read.
export function useChatRoute(company: Company | null, companies: Company[], loading: boolean, selectCompany: (id: string) => void) {
  const [params, setParams] = useSearchParams();
  const [restoreId, setRestoreId] = useState(() => params.get('chat_id'));
  const [restored, setRestored] = useState<ChatState | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [fetching, setFetching] = useState(!!restoreId);
  const [attempt, setAttempt] = useState(0);
  const previousCompany = useRef<string | null>(null);
  const expectedCompany = useRef<string | null>(null);
  const manualOverride = useRef(false);
  const writeUrl = useCallback((chat: Chat | null) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (chat) next.set('chat_id', chat.id); else next.delete('chat_id');
      return next;
    }, { replace: true });
  }, [setParams]);

  useEffect(() => {
    if (!restoreId) { setFetching(false); return; }
    const controller = new AbortController();
    setFetching(true); setError(null);
    void analyticsApi.chat(restoreId, controller.signal).then((chat) => {
      if (controller.signal.aborted) return;
      if (chat.id !== restoreId || !chat.company_id || !chat.event_id || typeof chat.event_title !== 'string') throw normalizeError(502, { message: 'Не удалось определить контекст диалога.' });
      setRestored(chat);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) { setRestored(null); setError(reason); } })
      .finally(() => { if (!controller.signal.aborted) setFetching(false); });
    return () => controller.abort();
  }, [restoreId, attempt]);

  useEffect(() => {
    const id = company?.id || null;
    if (previousCompany.current && id && previousCompany.current !== id && expectedCompany.current !== id) {
      manualOverride.current = true;
      setRestoreId(null); setRestored(null); setError(null); writeUrl(null);
    }
    if (id === expectedCompany.current) expectedCompany.current = null;
    previousCompany.current = id;
  }, [company?.id, writeUrl]);

  useEffect(() => {
    if (!restored || loading || manualOverride.current) return;
    if (!companies.some((item) => item.id === restored.company_id)) {
      setRestored(null); setError(normalizeError(403, { message: 'Нет доступа к компании диалога.' })); return;
    }
    if (company?.id !== restored.company_id) {
      expectedCompany.current = restored.company_id;
      selectCompany(restored.company_id);
    }
  }, [restored, companies, loading, company?.id, selectCompany]);

  return {
    chat: restored?.company_id === company?.id ? restored : null,
    restoring: fetching || (!!restored && restored.company_id !== company?.id),
    error, writeUrl,
    retry: () => setAttempt((value) => value + 1),
    dismiss() { setRestoreId(null); setRestored(null); setError(null); writeUrl(null); },
  };
}

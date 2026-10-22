import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../shared/api/errors';

type Load<T> = (signal: AbortSignal, limit: number, offset: number) => Promise<T[]>;
const PAGE_SIZE = 50;

// Shared by operator lists; refresh cancels old pages, errors never imply an empty result.
export function useAdminList<T extends { id: string }>(load: Load<T>) {
  const [items, setItems] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [hasMore, setHasMore] = useState(false);
  const active = useRef<AbortController | null>(null);
  const nextOffset = useRef(0);
  const lastOffset = useRef(0);
  const request = useCallback((offset: number) => {
    active.current?.abort();
    const controller = new AbortController(); active.current = controller;
    lastOffset.current = offset;
    setLoading(true); setError(null);
    if (offset === 0) { setItems([]); setHasMore(false); }
    void load(controller.signal, PAGE_SIZE, offset).then((page) => {
      if (controller.signal.aborted) return;
      setItems((current) => [...new Map([...(offset ? current : []), ...page].map((row) => [row.id, row])).values()]);
      nextOffset.current = offset + page.length;
      setHasMore(page.length === PAGE_SIZE);
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) { setItems([]); setHasMore(false); }
      setError(reason);
    }).finally(() => { if (!controller.signal.aborted) { active.current = null; setLoading(false); } });
  }, [load]);
  useEffect(() => { request(0); return () => active.current?.abort(); }, [request]);
  return {
    items, loading, error, hasMore,
    refresh: useCallback(() => request(0), [request]),
    more() { if (!active.current) request(nextOffset.current); },
    retry() { request(lastOffset.current); },
    replace(row: T) { setItems((current) => current.map((item) => item.id === row.id ? row : item)); },
    deny(reason: unknown) { active.current?.abort(); setItems([]); setHasMore(false); setLoading(false); setError(reason); },
  };
}

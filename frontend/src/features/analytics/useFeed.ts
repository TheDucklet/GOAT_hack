import { useEffect, useRef, useState } from 'react';
import type { Feed, FeedItem, FeedSnapshot, FeedSnapshotItem } from '../../shared/api/types';
import { ApiError, normalizeError } from '../../shared/api/errors';
import { analyticsApi } from './api';

export const FEED_PAGE_SIZE = 20;
export const FEED_WAIT_MS = 120_000;
export const FEED_CHECK_MS = 45_000;
function isSnapshot(page: Feed | FeedSnapshot): page is FeedSnapshot {
  return 'schema_version' in page && page.schema_version === 'v2' && 'snapshot_id' in page && typeof page.snapshot_id === 'string';
}

export function useFeed(companyId: string) {
  const [request, setRequest] = useState({ offset: 0, attempt: 0 });
  const [items, setItems] = useState<(FeedItem | FeedSnapshotItem)[]>([]);
  const [snapshot, setSnapshot] = useState<FeedSnapshot | null>(null);
  const snapshotId = useRef<string | undefined>(undefined);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    const deadline = Date.now() + FEED_WAIT_MS;
    setLoading(true); setError(null);
    async function read() {
      if (busy || controller.signal.aborted) return;
      busy = true; clearTimeout(timer);
      try {
        const args = [companyId, FEED_PAGE_SIZE, request.offset, controller.signal] as const;
        const page = snapshotId.current ? await analyticsApi.feed(...args, snapshotId.current) : await analyticsApi.feed(...args);
        if (controller.signal.aborted) return;
        if ('schema_version' in page && !isSnapshot(page)) {
          throw normalizeError(502, { code: 'unsupported_feed', message: 'Формат ленты изменился. Обновите приложение перед использованием выводов.' });
        }
        const v2 = isSnapshot(page) ? page : null;
        if (v2) {
          if (snapshotId.current && v2.snapshot_id !== snapshotId.current) {
            throw normalizeError(502, { message: 'Сервер вернул другой снимок ленты. Обновите ленту.' });
          }
          snapshotId.current = v2.snapshot_id; setSnapshot(v2);
        }
        setItems((previous) => [...new Map([
          ...(request.offset === 0 ? [] : previous), ...page.items,
        ].map((item) => [item.event_id, item])).values()]);
        const next = v2 ? v2.next_offset : page.offset + page.items.length;
        setTotal(page.total); setNextOffset(next ?? 0);
        setHasMore(Boolean(v2 || page.items.length) && next !== null && next < page.total); setError(null);
        const pending = v2 && ['queued', 'running'].includes(v2.generation_status);
        setLoading(Boolean(pending));
        if (pending && Date.now() >= deadline) {
          throw normalizeError(408, { code: 'polling_timeout', message: 'Подготовка ещё не завершена. Проверьте статус позже.' });
        }
        if (v2 && !v2.stale) timer = setTimeout(() => void read(), pending ? 2000 : FEED_CHECK_MS);
      } catch (reason: unknown) {
        if (controller.signal.aborted) return;
        if (reason instanceof ApiError && ([401, 403].includes(reason.status) || reason.body.code === 'unsupported_feed')) {
          setItems([]); setSnapshot(null); setTotal(0); setHasMore(false);
        }
        setError(reason); setLoading(false);
      } finally { busy = false; }
    }
    const check = () => { if (document.visibilityState === 'visible') void read(); };
    void read();
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    return () => {
      controller.abort(); clearTimeout(timer);
      window.removeEventListener('focus', check);
      document.removeEventListener('visibilitychange', check);
    };
  }, [companyId, request]);

  return {
    items, total, snapshot, loading, error, hasMore,
    loadMore() {
      if (loading || error || !hasMore) return;
      setLoading(true);
      setRequest((current) => ({ ...current, offset: nextOffset }));
    },
    retry() {
      setLoading(true);
      setRequest((current) => ({
        offset: error instanceof ApiError && error.status === 403 ? 0 : current.offset,
        attempt: current.attempt + 1,
      }));
    },
    refresh() {
      snapshotId.current = undefined; setSnapshot(null);
      setItems([]); setTotal(0); setHasMore(false); setLoading(true); setError(null);
      setRequest((current) => ({ offset: 0, attempt: current.attempt + 1 }));
    },
  };
}

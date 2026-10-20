import { useEffect, useState } from 'react';
import type { FeedItem } from '../../shared/api/types';
import { ApiError } from '../../shared/api/errors';
import { analyticsApi } from './api';

export const FEED_PAGE_SIZE = 20;

export function useFeed(companyId: string) {
  const [request, setRequest] = useState({ offset: 0, attempt: 0 });
  const [items, setItems] = useState<FeedItem[]>([]);
  const [total, setTotal] = useState(0);
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    void analyticsApi.feed(companyId, FEED_PAGE_SIZE, request.offset, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setItems((previous) => [...new Map([
        ...(request.offset === 0 ? [] : previous), ...page.items,
      ].map((item) => [item.event_id, item])).values()]);
      const next = page.offset + page.items.length;
      setTotal(page.total); setNextOffset(next);
      setHasMore(page.items.length > 0 && next < page.total);
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 403) {
        setItems([]); setTotal(0); setHasMore(false);
      }
      setError(reason);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [companyId, request]);

  return {
    items, total, loading, error, hasMore,
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
      setItems([]); setTotal(0); setHasMore(false); setLoading(true); setError(null);
      setRequest((current) => ({ offset: 0, attempt: current.attempt + 1 }));
    },
  };
}

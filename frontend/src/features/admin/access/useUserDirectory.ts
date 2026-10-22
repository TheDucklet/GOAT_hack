import { useEffect, useState } from 'react';
import { adminApi } from '../api';
import type { User } from '../../../shared/api/types';

// A-03 memberships expose user_id only. Read the paginated directory once, rather than one request per row.
export function useUserDirectory() {
  const [users, setUsers] = useState<Map<string, User>>(new Map());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setUsers(new Map());
    void (async () => {
      const directory = new Map<string, User>();
      for (let offset = 0; ; offset += 200) {
        controller.signal.throwIfAborted();
        const page = await adminApi.users(controller.signal, 200, offset);
        page.forEach((user) => directory.set(user.id, user));
        if (page.length < 200) break;
      }
      if (!controller.signal.aborted) setUsers(directory);
    })().catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);
  return { users, loading, error, refresh: () => setAttempt((value) => value + 1) };
}

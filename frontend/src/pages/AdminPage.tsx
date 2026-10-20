import { useEffect, useState } from 'react';
import { api } from '../api';
import type { AdminStats } from '../api/types';
import { ErrorNotice } from '../components/ErrorNotice';

export function AdminPage() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(null); setStats(null);
    void api.adminStats(controller.signal).then((result) => { if (!controller.signal.aborted) setStats(result); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason); });
    return () => controller.abort();
  }, [attempt]);
  return <><span className="eyebrow">Управление сервисом</span><h1>Администрирование</h1><p className="page-lead">Доступ проверяет сервер.</p>
    {error != null ? <ErrorNotice error={error} retry={() => setAttempt((value) => value + 1)} /> : stats ? <div className="info-grid"><article className="panel"><p>Оценок полезности</p><strong className="stat">{stats.positive_feedback + stats.negative_feedback}</strong></article><article className="panel"><p>Заданий с ошибкой</p><strong className="stat">{stats.failed_jobs}</strong></article></div> : <p role="status">Проверяем доступ…</p>}
  </>;
}

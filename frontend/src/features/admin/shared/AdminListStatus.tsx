import type { ReactNode } from 'react';
import { ErrorNotice } from '../../../shared/ui/ErrorNotice';

export function AdminListStatus({ loading, error, empty, hasMore, retry, more, children }: {
  loading: boolean; error: unknown; empty: boolean; hasMore: boolean; retry(): void; more(): void; children: ReactNode;
}) {
  return <>
    {error != null && <ErrorNotice error={error} retry={retry} />}
    {children}
    {loading && <p role="status">Загружаем список…</p>}
    {!loading && !error && empty && <p className="panel">Записей пока нет.</p>}
    {hasMore && !error && <button className="button secondary" disabled={loading} onClick={more}>Загрузить ещё</button>}
  </>;
}

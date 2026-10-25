import { Link } from 'react-router-dom';
import { useEffect, useRef } from 'react';
import { useCompanySelection } from '../companies/CompanyProvider';
import type { Chat } from '../../shared/api/types';
import { ErrorNotice } from '../../shared/ui/ErrorNotice';
import { InsightNotice } from '../../shared/ui/InsightNotice';
import { ApiError } from '../../shared/api/errors';
import { AnalyticsSelectionProvider, useAnalyticsSelection } from './AnalyticsSelection';
import { FeedEvent } from './FeedEvent';
import { ChatPanel, InsightPanel } from './EventWorkspace';
import { useFeed } from './useFeed';
import { useChatRoute } from './chat/useChatRoute';
import { useDismissals } from './interactions/useDismissals';

function AnalyticsWorkspace({ writeUrl }: { writeUrl(chat: Chat | null): void }) {
  const { companyId, event, chat, selectEvent } = useAnalyticsSelection();
  useEffect(() => { writeUrl(chat); }, [chat, writeUrl]);
  const feed = useFeed(companyId);
  const previousSnapshot = useRef<string | undefined>(undefined);
  useEffect(() => {
    const id = feed.snapshot?.snapshot_id;
    if (feed.snapshot?.stale || (id && previousSnapshot.current && previousSnapshot.current !== id)) selectEvent(null);
    if (id) previousSnapshot.current = id;
  }, [feed.snapshot?.snapshot_id, feed.snapshot?.stale, selectEvent]);
  const dismissals = useDismissals(companyId, () => { selectEvent(null); feed.refresh(); }, () => { selectEvent(null); feed.refresh(); });
  const unavailableContext = feed.error instanceof ApiError && ([401, 403].includes(feed.error.status) || feed.error.body.code === 'unsupported_feed');
  useEffect(() => { if (unavailableContext) selectEvent(null); }, [unavailableContext, selectEvent]);
  return <><nav className="workspace-navigation" aria-label="Навигация по аналитике"><a href="#feed-heading">События и источники</a><a href="#insight-heading">Анализ</a><a href="#chat-heading">Чат</a></nav><div className="analytics-grid">
    <section className="feed" aria-labelledby="feed-heading" aria-busy={feed.loading}>
      <div className="feed-heading"><div><h2 id="feed-heading">Персональная лента</h2>
        <p className="muted">Выводы для вашей компании, их основания и актуальность</p></div>
        <button className="button secondary" disabled={feed.loading} onClick={() => { selectEvent(null); feed.refresh(); }}>Обновить ленту</button>
      </div>
      <InsightNotice />
      {feed.snapshot && <div className="feed-status" role="status">
        {feed.snapshot.stale ? 'Данные изменились. Обновите ленту перед использованием выводов.'
          : ({ queued: 'Персональная лента в очереди…', running: 'Готовим персональные инсайты…',
            ready: 'Подготовка ленты завершена.', partial: 'Часть анализов недоступна. Готовые выводы показаны отдельно.',
            failed: 'Не удалось подготовить ленту. Готовые инсайты не получены.', deferred: 'Подготовка отложена. Сохранённые данные остаются доступны.', stale: 'Нужно обновить ленту.' }[feed.snapshot.generation_status])}
        {['failed', 'deferred'].includes(feed.snapshot.generation_status) && <button className="button secondary" disabled={feed.loading} onClick={feed.retry}>Проверить статус</button>}
      </div>}
      {feed.error != null && <ErrorNotice error={feed.error} retry={feed.retry} />}
      {dismissals.error != null && <ErrorNotice error={dismissals.error} retry={dismissals.retry} />}
      <details className="hidden-events"><summary>Скрытые события ({dismissals.rows.length})</summary>
        {dismissals.loading && <p role="status">Загружаем личные скрытия…</p>}
        {!dismissals.loading && !dismissals.rows.length && <p>У вас нет скрытых событий.</p>}
        <ul>{dismissals.rows.map((row) => <li key={`${row.event_id}:${row.version}`}><span>{row.title || `Событие ${row.event_id}`}</span>
          <button className="button secondary" disabled={dismissals.busy || dismissals.loading} onClick={() => void dismissals.mutate({ event_id: row.event_id, version: row.version, hidden: false })}>Вернуть</button></li>)}</ul>
      </details>
      {feed.items.length > 0 && <>
        <p className="feed-count">Показано {feed.items.length} из {feed.total}</p>
        <ul className="feed-list" aria-label="События">{feed.items.map((item) => <li key={item.event_id}>
          <FeedEvent event={item} stale={feed.snapshot?.stale} selected={event?.event_id === item.event_id} onSelect={() => selectEvent(item, !feed.snapshot?.stale && 'generation_status' in item && item.generation_status === 'ready' && typeof item.insight_id === 'string' ? item.insight_id : null)} />
          <button className="button secondary" disabled={dismissals.busy || dismissals.loading} onClick={() => void dismissals.mutate({ event_id: item.event_id, hidden: true })}>Скрыть событие «{item.title}»</button>
        </li>)}</ul>
      </>}
      {feed.loading && <p className="feed-loading" role="status">{feed.items.length ? 'Загружаем следующие события…' : 'Загружаем события…'}</p>}
      {!feed.loading && !feed.error && !feed.items.length && (!feed.snapshot || feed.snapshot.generation_status === 'ready') && <div className="panel empty-state"><h3>Нет подходящих событий</h3><p>Обновите ленту позже или выберите другую компанию.</p></div>}
      {feed.hasMore && !feed.error && <button className="button secondary feed-more" disabled={feed.loading} onClick={feed.loadMore}>Загрузить ещё</button>}
    </section>
    <aside className="event-workspace" aria-label="Выбранное событие"><InsightPanel hide={event && !dismissals.busy && !dismissals.loading ? (insightId) => void dismissals.mutate({ event_id: event.event_id, insight_id: insightId, hidden: true }) : undefined} /><ChatPanel /></aside>
  </div></>;
}

export function AnalyticsPage({ userId }: { userId: string }) {
  const selection = useCompanySelection();
  const { company } = selection;
  const route = useChatRoute(company, selection.companies, selection.loading, selection.selectCompany);
  if (route.restoring) return <p role="status">Восстанавливаем контекст диалога…</p>;
  if (route.error) return <><ErrorNotice error={route.error} retry={route.retry} /><button className="button secondary" onClick={route.dismiss}>Открыть ленту без диалога</button></>;
  if (!company) return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><section className="panel empty-state"><h2>Нужен доступ к компании</h2><p>Лента станет доступна после подтверждения заявки администратором.</p><Link className="button primary" to="/app/companies">Компании и профиль</Link></section></>;
  return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><p className="page-lead">{company.name}</p>
    <AnalyticsSelectionProvider key={`${company.id}:${route.chat?.id || 'feed'}`} companyId={company.id} userId={userId}
      initialChat={route.chat || undefined} initialEvent={route.chat ? { event_id: route.chat.event_id, title: route.chat.event_title, summary: null, published_at: null, status: 'restored', rank_score: 0, sources: [], relevance_reasons: [] } : undefined}>
      <AnalyticsWorkspace writeUrl={route.writeUrl} />
    </AnalyticsSelectionProvider>
  </>;
}

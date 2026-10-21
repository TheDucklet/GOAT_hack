import { Link } from 'react-router-dom';
import { useEffect } from 'react';
import { useCompany } from '../companies/CompanyProvider';
import { ErrorNotice } from '../../shared/ui/ErrorNotice';
import { InsightNotice } from '../../shared/ui/InsightNotice';
import { ApiError } from '../../shared/api/errors';
import { AnalyticsSelectionProvider, useAnalyticsSelection } from './AnalyticsSelection';
import { FeedEvent } from './FeedEvent';
import { ChatPanel, InsightPanel } from './EventWorkspace';
import { useFeed } from './useFeed';

function AnalyticsWorkspace() {
  const { companyId, event, selectEvent } = useAnalyticsSelection();
  const feed = useFeed(companyId);
  const forbidden = feed.error instanceof ApiError && feed.error.status === 403;
  useEffect(() => { if (forbidden) selectEvent(null); }, [forbidden, selectEvent]);
  return <div className="analytics-grid">
    <section className="feed" aria-labelledby="feed-heading" aria-busy={feed.loading}>
      <div className="feed-heading"><div><h2 id="feed-heading">Персональная лента</h2>
        <p className="muted">События с учётом контекста компании и ваших интересов</p></div>
        <button className="button secondary" disabled={feed.loading} onClick={() => { selectEvent(null); feed.refresh(); }}>Обновить ленту</button>
      </div>
      {feed.error != null && <ErrorNotice error={feed.error} retry={feed.retry} />}
      {feed.items.length > 0 && <>
        <p className="feed-count">Показано {feed.items.length} из {feed.total}</p>
        <ul className="feed-list" aria-label="События">{feed.items.map((item) => <li key={item.event_id}>
          <FeedEvent event={item} selected={event?.event_id === item.event_id} onSelect={() => selectEvent(item)} />
        </li>)}</ul>
      </>}
      {feed.loading && <p className="feed-loading" role="status">{feed.items.length ? 'Загружаем следующие события…' : 'Загружаем события…'}</p>}
      {!feed.loading && !feed.error && !feed.items.length && <div className="panel empty-state"><h3>Нет подходящих событий</h3><p>Обновите ленту позже или выберите другую компанию.</p></div>}
      {feed.hasMore && !feed.error && <button className="button secondary feed-more" disabled={feed.loading} onClick={feed.loadMore}>Загрузить ещё</button>}
    </section>
    <aside className="event-workspace" aria-label="Выбранное событие"><InsightPanel /><ChatPanel /></aside>
  </div>;
}

export function AnalyticsPage() {
  const company = useCompany();
  if (!company) return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><section className="panel empty-state"><h2>Нужен доступ к компании</h2><p>Лента станет доступна после подтверждения заявки администратором.</p><Link className="button primary" to="/app/companies">Компании и профиль</Link></section></>;
  return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><p className="page-lead">{company.name}</p>
    <AnalyticsSelectionProvider companyId={company.id}><AnalyticsWorkspace /></AnalyticsSelectionProvider>
    <InsightNotice />
  </>;
}

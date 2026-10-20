import { useCompany } from '../layout/AppLayout';

export function AnalyticsPage() {
  const company = useCompany();
  return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><p className="page-lead">{company?.name || 'Компания пока не выбрана'}</p><section className="panel empty-state"><span className="empty-symbol" aria-hidden="true">↗</span><h2>Пространство для анализа</h2><p>Здесь появятся лента событий, карточка влияния и диалог с аналитикой.</p><p className="muted">Сервис аналитики пока не подключён.</p></section></>;
}

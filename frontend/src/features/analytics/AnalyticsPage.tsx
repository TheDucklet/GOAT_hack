import { useCompany } from '../companies/CompanyProvider';
import { Link } from 'react-router-dom';

export function AnalyticsPage() {
  const company = useCompany();
  if (!company) return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><section className="panel empty-state"><h2>Нужен доступ к компании</h2><p>Лента станет доступна после подтверждения заявки администратором.</p><Link className="button primary" to="/app/companies">Компании и профиль</Link></section></>;
  return <><span className="eyebrow">Персональный контекст</span><h1>Бизнес-аналитика</h1><p className="page-lead">{company?.name || 'Компания пока не выбрана'}</p><section className="panel empty-state"><span className="empty-symbol" aria-hidden="true">↗</span><h2>Пространство для анализа</h2><p>Здесь появятся лента событий, карточка влияния и диалог с аналитикой.</p><p className="muted">Сервис аналитики пока не подключён.</p></section></>;
}

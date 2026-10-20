import { Link } from 'react-router-dom';
import { useCompany } from '../companies/CompanyProvider';

export function OverviewPage() {
  const company = useCompany();
  return <><span className="eyebrow">Рабочее пространство</span><h1>Ваш бизнес в фокусе</h1><p className="page-lead">{company ? company.name : 'Выберите доступную компанию в верхней панели.'}</p>
    <section className="analytics-entry"><div><span className="pill">Бизнес-аналитика</span><h2>Что меняется вокруг<br />вашей компании</h2><p>Персональная лента событий и аналитика их возможного влияния.</p><Link className="button primary" to="/app/analytics">Открыть бизнес-аналитику <span aria-hidden="true">↗</span></Link></div><div className="entry-art" aria-hidden="true"><div /><div /><div /><span>А</span></div></section>
    <div className="info-grid"><article className="panel"><span className="step">01</span><h3>Значимые события</h3><p>С учётом контекста компании и ваших информационных потребностей.</p></article><article className="panel"><span className="step">02</span><h3>Проверяемые основания</h3><p>Факты, банковские материалы и выводы AI представлены раздельно.</p></article><article className="panel"><span className="step">03</span><h3>Уточняющие вопросы</h3><p>Диалог помогает разобраться в предпосылках и недостающих данных.</p></article></div>
  </>;
}

import { useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { useCompanySelection } from '../../features/companies/CompanyProvider';
import { useAuth } from '../../features/auth/AuthProvider';
import { ErrorNotice } from '../../shared/ui/ErrorNotice';
import { config } from '../../shared/config';

export function AppLayout() {
  const { state, logout } = useAuth();
  const { company, companies: availableCompanies, loading, error: companyError, selectCompany, retry } = useCompanySelection();
  const [error, setError] = useState<unknown>(null);
  const [signingOut, setSigningOut] = useState(false);
  if (state.status !== 'authenticated') return null;
  const userName = state.session.email.split('@')[0];
  return <>
    <a className="skip-link" href="#main">К содержанию</a>
    <header className="header">
      <NavLink className="brand" to="/app" aria-label="Альфа-Бизнес, главная"><span className="brand-mark">А</span><span>Альфа-Бизнес</span></NavLink>
      <div className="header-company">
        <label htmlFor="company">Компания</label>
        <select id="company" value={company?.id || ''} disabled={loading || !availableCompanies.length} onChange={(event) => selectCompany(event.target.value)}>
          {!availableCompanies.length && <option value="">{loading ? 'Загрузка…' : 'Нет доступных компаний'}</option>}
          {availableCompanies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </div>
      <div className="user-summary"><span className="avatar" aria-hidden="true">{userName?.slice(0, 1).toUpperCase()}</span><span><strong>{userName}</strong><small>{state.session.email}</small></span></div>
      <button className="button secondary" disabled={signingOut} onClick={async () => {
        setSigningOut(true); setError(null);
        try { await logout(); } catch (reason) { setError(reason); }
        finally { setSigningOut(false); }
      }}>{signingOut ? 'Выходим…' : 'Выйти'}</button>
    </header>
    {import.meta.env.DEV && config.apiMode === 'mock' && <div className="mock-banner" role="status">Демонстрационный режим · синтетические данные · backend не подключён</div>}
    <div className="shell">
      <aside className="sidebar"><div className="sidebar-label">Рабочее пространство</div><nav aria-label="Основная навигация">
        <NavLink to="/app" end>Обзор</NavLink>
        <NavLink to="/app/companies">Компании и профиль</NavLink>
        <NavLink to="/app/analytics">Бизнес-аналитика <span aria-hidden="true">↗</span></NavLink>
        {state.session.system_role === 'admin' && <NavLink to="/admin">Администрирование</NavLink>}
      </nav><p className="sidebar-note">Внешние события.<br />Контекст вашего бизнеса.</p></aside>
      <main id="main" className="main">
        {error != null && <ErrorNotice error={error} />}
        {companyError != null && <ErrorNotice error={companyError} retry={retry} />}
        {!loading && !companyError && !availableCompanies.length && <p className="membership-notice" role="status">Нет доступных компаний. Доступ появится после подтверждения членства администратором. <Link to="/app/companies">Подать заявку или проверить статус</Link></p>}
        {loading ? <p role="status">Загружаем компании…</p> : <Outlet key={company?.id || ''} />}
      </main>
    </div>
  </>;
}

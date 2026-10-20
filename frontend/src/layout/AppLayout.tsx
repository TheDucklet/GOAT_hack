import { createContext, useContext, useEffect, useState } from 'react';
import { Link, NavLink, Outlet } from 'react-router-dom';
import { api } from '../api';
import type { Company } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { ErrorNotice } from '../components/ErrorNotice';
import { config } from '../config';

const CompanyContext = createContext<Company | null>(null);
const CompaniesContext = createContext<Company[]>([]);
export const useCompany = () => useContext(CompanyContext);
export const useCompanies = () => useContext(CompaniesContext);

export function AppLayout() {
  const { state, logout } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [signingOut, setSigningOut] = useState(false);
  const activeCompanyIds = state.status === 'authenticated' ? state.session.memberships.filter((item) => item.status === 'active').map((item) => item.company_id) : [];
  const accessKey = JSON.stringify(activeCompanyIds.sort());
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void api.companies(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setCompanies(result);
      setCompanyId((current) => result.some((company) => company.id === current) ? current : result[0]?.id || '');
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, accessKey]);
  if (state.status !== 'authenticated') return null;
  const availableCompanies = companies.filter((item) => activeCompanyIds.includes(item.id));
  const company = availableCompanies.find((item) => item.id === companyId) || null;
  const userName = state.session.email.split('@')[0];
  return <CompanyContext.Provider value={company}><CompaniesContext.Provider value={availableCompanies}>
    <a className="skip-link" href="#main">К содержанию</a>
    <header className="header">
      <NavLink className="brand" to="/app" aria-label="Альфа-Бизнес, главная"><span className="brand-mark">А</span><span>Альфа-Бизнес</span></NavLink>
      <div className="header-company">
        <label htmlFor="company">Компания</label>
        <select id="company" value={company?.id || ''} disabled={loading || !availableCompanies.length} onChange={(event) => setCompanyId(event.target.value)}>
          {!availableCompanies.length && <option value="">{loading ? 'Загрузка…' : 'Нет доступных компаний'}</option>}
          {availableCompanies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </div>
      <div className="user-summary"><span className="avatar" aria-hidden="true">{userName?.slice(0, 1).toUpperCase()}</span><span><strong>{userName}</strong><small>{state.session.email}</small></span></div>
      <button className="button secondary" disabled={signingOut} onClick={async () => {
        setSigningOut(true);
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
        {error != null && <ErrorNotice error={error} retry={() => setAttempt((value) => value + 1)} />}
        {!loading && !error && !availableCompanies.length && <p className="membership-notice" role="status">Нет доступных компаний. Доступ появится после подтверждения членства администратором. <Link to="/app/companies">Подать заявку или проверить статус</Link></p>}
        {loading ? <p role="status">Загружаем компании…</p> : <Outlet key={companyId} />}
      </main>
    </div>
  </CompaniesContext.Provider></CompanyContext.Provider>;
}

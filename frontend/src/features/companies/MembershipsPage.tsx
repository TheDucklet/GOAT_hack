import { useState } from 'react';
import { companiesApi } from './api';
import { useAuth } from '../auth/AuthProvider';
import { ErrorNotice } from '../../shared/ui/ErrorNotice';
import { MembershipForm } from './MembershipForm';
import { useCompanies } from './CompanyProvider';
import type { Membership } from '../../shared/api/types';

const statuses: Record<Membership['status'], string> = { active: 'Доступ открыт', pending: 'Ожидает подтверждения', rejected: 'Заявка отклонена' };

export function MembershipsPage() {
  const { state, reloadSession, recordMembership } = useAuth();
  const companies = useCompanies();
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (state.status !== 'authenticated') return null;
  const memberships = state.session.memberships;

  async function refresh() {
    setRefreshing(true); setError(null);
    try { await reloadSession(); } catch (reason) { setError(reason); }
    finally { setRefreshing(false); }
  }

  return <><span className="eyebrow">Ваш доступ и персонализация</span>
    <div className="page-heading"><div><h1>Компании и профиль</h1><p className="page-lead">Должность и интересы задаются отдельно для каждой компании.</p></div>
      <button className="button secondary" disabled={refreshing} onClick={refresh}>{refreshing ? 'Обновляем…' : 'Обновить доступ'}</button></div>
    {error != null && <ErrorNotice error={error} retry={refresh} />}
    <div className="membership-grid">
      <section className="membership-list" aria-label="Мои членства"><h2>Мои компании</h2>
        {!memberships.length && <div className="panel"><h3>Вы ещё не состоите в компании</h3><p>Отправьте заявку. Администратор подтвердит доступ, после чего компания появится в верхней панели.</p></div>}
        {memberships.map((membership) => {
          const name = companies.find((item) => item.id === membership.company_id)?.name || membership.company_id;
          return <article className="panel membership-card" key={membership.id} aria-label={`Членство: ${name}`}>
            <div className="membership-heading"><h3>{name}</h3><span className={`membership-status ${membership.status}`}>{statuses[membership.status]}</span></div>
            <p className="membership-id">Идентификатор компании: {membership.company_id}</p>
            {membership.status === 'pending' && <p className="membership-help">Пока заявка ожидает подтверждения, лента компании недоступна.</p>}
            {membership.status === 'rejected' && <p className="membership-help">Обратитесь к администратору компании, чтобы уточнить причину и возможность доступа.</p>}
            <MembershipForm membership={membership} label={`Профиль: ${name}`} save={(profile) => companiesApi.updateProfile(membership.id, profile)} onSaved={recordMembership} />
          </article>;
        })}
      </section>
      <section className="panel membership-request"><h2>Доступ к новой компании</h2><p className="membership-help">Заявку проверит администратор. До подтверждения данные компании закрыты.</p>
        <MembershipForm label="Заявка на компанию" save={(profile, companyId) => companiesApi.requestMembership({ ...profile, company_id: companyId })} onSaved={recordMembership} />
      </section>
    </div>
  </>;
}

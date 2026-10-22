import { adminApi } from '../api';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { AccessList } from './AccessList';
import { useAdminList } from './useAdminList';
import { useAccessAction } from './useAccessAction';
import { useUserDirectory } from './useUserDirectory';

const statuses = { pending: 'Ожидает подтверждения', active: 'Доступ открыт', rejected: 'Заявка отклонена' };

export function AdminMembershipsPage() {
  const list = useAdminList(adminApi.memberships);
  const directory = useUserDirectory();
  const action = useAccessAction(list.replace, list.deny);
  const error = list.error || directory.error;
  const loading = list.loading || directory.loading;
  const refresh = () => { list.refresh(); directory.refresh(); };
  return <>
    <div className="page-heading"><div><span className="eyebrow">Управление доступом</span><h1>Заявки и доступ к компаниям</h1>
      <p className="page-lead">Проверьте пользователя и идентификатор компании перед подтверждением заявки.</p></div>
      <button className="button secondary" disabled={loading || !!action.action} onClick={refresh}>Обновить список</button></div>
    {action.success && !error && <p role="status" className="success-notice">{action.success}</p>}
    <AccessList loading={loading} error={error} empty={!list.items.length} hasMore={list.hasMore} more={list.more} retry={refresh}>
      {!error && !directory.loading && <ul className="access-list" aria-label="Членства и заявки">{list.items.map((membership) => {
        const user = directory.users.get(membership.user_id);
        const name = user?.email || membership.user_id;
        return <li key={membership.id}><article className="panel access-card" aria-label={`Заявка: ${name}, ${membership.company_id}`}>
          <div className="access-heading"><h2>{name}</h2><span className={`access-status ${membership.status}`}>{statuses[membership.status]}</span></div>
          <p>Компания: <code>{membership.company_id}</code></p><p>Идентификатор пользователя: <code>{membership.user_id}</code></p>
          <p>Идентификатор членства: <code>{membership.id}</code></p><p>Должность: {membership.position_text || 'Не указана'}</p>
          <p>Интересы: {membership.interests.length ? membership.interests.join('; ') : 'Не указаны'}</p>
          {user?.status === 'blocked' && <p className="access-warning">Пользователь заблокирован. Подтверждение членства не разблокирует учётную запись.</p>}
          <div className="access-actions">{(['active', 'rejected'] as const).filter((status) => status !== membership.status).map((status) => <button key={status} className="button secondary" disabled={loading || !!action.action} onClick={() => {
            action.prepare({ id: membership.id, status, title: `${status === 'active' ? 'Подтвердить доступ' : 'Отклонить доступ'}: ${name}?`,
              description: `${name}. Компания: ${membership.company_id}. ${status === 'active' ? 'Членство станет активным; заблокированная учётная запись останется заблокированной.' : 'Данные этой компании станут недоступны пользователю.'}`,
              success: `${name} · ${membership.company_id}: ${status === 'active' ? 'доступ подтверждён. Пользователю нужно нажать «Обновить доступ» на странице компаний.' : 'заявка отклонена, доступ закрыт.'}`,
              save: (signal) => adminApi.updateMembership(membership.id, { status }, signal) });
          }}>{status === 'active' ? 'Подтвердить доступ' : membership.status === 'active' ? 'Отозвать доступ' : 'Отклонить заявку'}</button>)}</div>
        </article></li>;
      })}</ul>}
    </AccessList>
    {action.action && <ConfirmDialog {...action.action} busy={action.busy} error={action.error} confirm={() => void action.confirm()} cancel={action.cancel} />}
  </>;
}

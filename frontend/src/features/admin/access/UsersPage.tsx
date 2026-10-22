import { adminApi } from '../api';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { AccessList } from './AccessList';
import { useAdminList } from './useAdminList';
import { useAccessAction } from './useAccessAction';

export function UsersPage({ currentUserId }: { currentUserId: string }) {
  const list = useAdminList(adminApi.users);
  const action = useAccessAction(list.replace, list.deny);
  return <>
    <div className="page-heading"><div><span className="eyebrow">Управление доступом</span><h1>Пользователи</h1>
      <p className="page-lead">Блокировка завершает все сессии пользователя. После разблокировки потребуется новый вход.</p></div>
      <button className="button secondary" disabled={list.loading || !!action.action} onClick={list.refresh}>Обновить список</button></div>
    {action.success && !list.error && <p role="status" className="success-notice">{action.success}</p>}
    <AccessList {...list} empty={!list.items.length}>
      <ul className="access-list" aria-label="Пользователи">{list.items.map((user) => <li key={user.id}>
        <article className="panel access-card" aria-label={`Пользователь: ${user.email}`}>
          <div className="access-heading"><h2>{user.email}</h2><span className={`access-status ${user.status}`}>{user.status === 'active' ? 'Активен' : 'Заблокирован'}</span></div>
          <p>Идентификатор пользователя: <code>{user.id}</code></p><p>Системная роль: {user.system_role === 'admin' ? 'Администратор' : 'Пользователь'}</p>
          {user.id === currentUserId ? <p>Это ваша учётная запись. Собственный доступ отозвать нельзя.</p> : <button className="button secondary" disabled={list.loading || !!action.action} onClick={() => {
            const status = user.status === 'active' ? 'blocked' : 'active';
            action.prepare({ id: user.id, status, title: `${status === 'blocked' ? 'Заблокировать' : 'Разблокировать'} ${user.email}?`,
              description: status === 'blocked' ? `Пользователь ${user.email} потеряет доступ ко всем компаниям. Все его текущие сессии будут отозваны.` : `Пользователь ${user.email} сможет войти заново. Прежние сессии не восстанавливаются; членства в компаниях сохраняются.`,
              success: status === 'blocked' ? `${user.email}: учётная запись заблокирована, сессии отозваны.` : `${user.email}: учётная запись разблокирована. Пользователь может войти заново.`,
              save: (signal) => adminApi.updateUser(user.id, { status }, signal) });
          }}>{user.status === 'active' ? 'Заблокировать' : 'Разблокировать'}</button>}
        </article>
      </li>)}</ul>
    </AccessList>
    {action.action && <ConfirmDialog {...action.action} busy={action.busy} error={action.error} confirm={() => void action.confirm()} cancel={action.cancel} />}
  </>;
}

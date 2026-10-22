import { adminApi } from '../api';
import { externalSourceUrl } from '../../../shared/api/evidence';
import { ConfirmDialog } from '../../../shared/ui/ConfirmDialog';
import { AdminListStatus } from '../shared/AdminListStatus';
import { useAdminList } from '../shared/useAdminList';
import { useAdminAction } from '../shared/useAdminAction';
import { MaterialJobStatus, processingLabels } from './MaterialJobStatus';
import { useMaterialJob } from './useMaterialJob';

export function publicationDate(value: string | null) {
  if (!value || Number.isNaN(Date.parse(value))) return 'Неизвестна';
  return new Date(value).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' }) + ' МСК';
}

export function NewsPage() {
  const list = useAdminList(adminApi.news);
  const action = useAdminAction(list.replace, list.deny);
  const work = useMaterialJob(list.refresh, list.deny);
  const disabled = list.loading || work.busy || !!action.action;
  return <>
    <div className="page-heading"><div><span className="eyebrow">Материалы сервиса</span><h1>Новости</h1>
      <p className="page-lead">Видимость новости действует для всех пользователей. Персональные скрытия инсайтов управляются отдельно.</p></div>
      <button className="button secondary" disabled={disabled} onClick={list.refresh}>Обновить список</button></div>
    {!list.error && <>
      <button className="button primary" disabled={disabled} onClick={() => work.start('Сбор новостей', async (signal) => ({ job: await adminApi.collectNews(signal) }))}>Собрать новости</button>
      <MaterialJobStatus state={work} />
      {action.success && <p role="status" className="success-notice">{action.success}</p>}
    </>}
    <AdminListStatus {...list} empty={!list.items.length}>
      <ul className="access-list" aria-label="Новости сервиса">{list.items.map((event) => <li key={event.id}>
        <article className="panel access-card" aria-label={`Новость: ${event.title}`}>
          <div className="access-heading"><h2>{event.title}</h2><span className={`access-status ${event.visible ? 'active' : 'rejected'}`}>{event.visible ? 'Видна пользователям' : 'Скрыта для всех'}</span></div>
          <p>Дата публикации: {publicationDate(event.published_at)}.</p><p>Обработка: {processingLabels[event.processing_status] || event.processing_status}.</p>
          <p>Идентификатор события: <code>{event.id}</code></p>
          {event.sources.length ? <ul className="material-sources" aria-label="Источники новости">{event.sources.map((source, index) => {
            const url = externalSourceUrl(source.url);
            const name = typeof source.name === 'string' ? source.name : 'Источник';
            return <li key={index}>{url ? <a href={url.href} target="_blank" rel="noopener noreferrer">{name} · {url.hostname} ↗</a> : <span>{name} · безопасная ссылка не указана</span>}</li>;
          })}</ul> : <p>Источник не указан.</p>}
          <div className="access-actions"><button className="button secondary" disabled={disabled} onClick={() => {
            const visible = !event.visible;
            action.prepare({ id: event.id, validate: (row) => row.visible === visible,
              title: visible ? 'Вернуть новость всем пользователям?' : 'Скрыть новость для всех пользователей?',
              description: event.title + '. Изменение затронет общую выдачу сервиса.',
              success: visible ? 'Новость возвращена в общую выдачу.' : 'Новость скрыта из общей выдачи.',
              save: async (signal) => { const result = await adminApi.visibility(event.id, visible, signal); return { ...event, ...result }; } });
          }}>{event.visible ? 'Скрыть для всех' : 'Вернуть всем'}</button>
          {['failed', 'done', 'pending_ai'].includes(event.processing_status) && <button className="button secondary" disabled={disabled} onClick={() => work.start('Анализ новости', async (signal) => ({ job: await adminApi.retryNews(event.id, signal) }))}>Повторить обработку</button>}</div>
        </article></li>)}</ul>
    </AdminListStatus>
    {action.action && <ConfirmDialog {...action.action} busy={action.busy} error={action.error} confirm={() => void action.confirm()} cancel={action.cancel} />}
  </>;
}

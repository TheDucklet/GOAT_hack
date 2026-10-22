import { adminApi } from '../api';
import type { AdminJob, Job } from '../../../shared/api/types';
import { EvidenceLink } from '../../../shared/ui/EvidenceLink';
import { AdminListStatus } from '../shared/AdminListStatus';
import { useAdminList } from '../shared/useAdminList';
import { MaterialJobStatus, processingLabels } from './MaterialJobStatus';
import { useMaterialJob } from './useMaterialJob';
import { publicationDate } from './NewsPage';

const kinds: Record<string, string> = { ingest_document: 'Индексация PDF', summarize: 'Анализ новости', collect_news: 'Сбор новостей', chat: 'Ответ в диалоге', insight: 'Подготовка анализа', feed_prepare: 'Подготовка ленты', focus: 'Профиль интересов' };
function retryFor(job: AdminJob): ((signal: AbortSignal) => Promise<Job>) | null {
  if (job.kind === 'collect_news') return (signal) => adminApi.collectNews(signal);
  if (job.kind === 'ingest_document' && job.target_id) return (signal) => adminApi.reindex(job.target_id!, signal);
  if (job.kind === 'summarize' && job.target_id) return (signal) => adminApi.retryNews(job.target_id!, signal);
  return null;
}

export function JobsPage() {
  const list = useAdminList(adminApi.jobs);
  const work = useMaterialJob(list.refresh, list.deny);
  return <>
    <div className="page-heading"><div><span className="eyebrow">Фоновая обработка</span><h1>Задания</h1>
      <p className="page-lead">Проверяйте уже принятое задание. Повтор обработки создаётся только явным действием после ошибки.</p></div>
      <button className="button secondary" disabled={work.busy || list.loading} onClick={list.refresh}>Обновить список</button></div>
    {!list.error && <MaterialJobStatus state={work} />}
    <AdminListStatus {...list} empty={!list.items.length}>
      <ul className="access-list" aria-label="Задания сервиса">{list.items.map((job) => {
        const retry = retryFor(job);
        return <li key={job.id}><article className="panel access-card" aria-label={`Задание: ${job.id}`}>
          <div className="access-heading"><h2>{kinds[job.kind] || job.kind}</h2><span className={`access-status ${job.status}`}>{processingLabels[job.status]}</span></div>
          <p>Идентификатор задания: <code>{job.id}</code></p>{job.target_id && <p>Материал: <code>{job.target_id}</code></p>}
          <p>Получено: {publicationDate(job.received_at || null)}. Попыток: {job.attempts ?? 0}.</p>
          {job.error && <p className="material-error" role="alert">{typeof job.error.message === 'string' ? job.error.message : 'Обработка завершилась ошибкой'}{typeof job.error.code === 'string' ? ` (${job.error.code})` : ''}</p>}
          {job.status === 'done' && typeof job.result?.chunks === 'number' && <p>Проиндексировано фрагментов: {job.result.chunks}.</p>}
          {job.kind === 'ingest_document' && job.status === 'done' && typeof job.result?.source_id === 'string' && <EvidenceLink id={job.result.source_id} label="Основание PDF" />}
          {['queued', 'running'].includes(job.status) && <button className="button secondary" disabled={work.busy || list.loading} onClick={() => work.monitor(job)}>Проверить задание</button>}
          {job.status === 'failed' && (retry ? <button className="button secondary" disabled={work.busy || list.loading} onClick={() => work.start(kinds[job.kind] || 'Повтор обработки', async (signal) => ({ job: await retry(signal) }))}>Повторить обработку</button> : <p>Повтор доступен на экране соответствующего анализа или диалога.</p>)}
        </article></li>;
      })}</ul>
    </AdminListStatus>
  </>;
}

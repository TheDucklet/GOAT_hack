import { useState } from 'react';
import { adminApi } from '../api';
import { normalizeError } from '../../../shared/api/errors';
import { FormField } from '../../../shared/ui/FormField';
import { EvidenceLink } from '../../../shared/ui/EvidenceLink';
import { AdminListStatus } from '../shared/AdminListStatus';
import { useAdminList } from '../shared/useAdminList';
import { MaterialJobStatus, processingLabels } from './MaterialJobStatus';
import { useMaterialJob } from './useMaterialJob';

const MAX_PDF_BYTES = 50 * 1024 * 1024;
export function DocumentsPage() {
  const list = useAdminList(adminApi.documents);
  const work = useMaterialJob(list.refresh, list.deny);
  const [file, setFile] = useState<File | null>(null);
  const [validation, setValidation] = useState('');
  return <>
    <div className="page-heading"><div><span className="eyebrow">Материалы банка</span><h1>Банковские PDF</h1>
      <p className="page-lead">Загрузите PDF для распознавания и обновления поискового корпуса. Неизвестная дата не подменяется датой загрузки.</p></div>
      <button className="button secondary" disabled={list.loading || work.busy} onClick={list.refresh}>Обновить список</button></div>
    {!list.error && <form className="panel material-upload" aria-label="Загрузка PDF" onSubmit={(event) => {
      event.preventDefault();
      if (!file || !file.name.toLowerCase().endsWith('.pdf') || file.size === 0 || file.size > MAX_PDF_BYTES) { setValidation('Выберите непустой PDF размером не более 50 МиБ.'); return; }
      setValidation('');
      work.start('Индексация PDF', async (signal) => {
        const signature = await file.slice(0, 5).text(); signal.throwIfAborted();
        if (signature !== '%PDF-') throw normalizeError(422, { message: 'Содержимое файла не является PDF.' });
        const result = await adminApi.upload(file, signal);
        if (!result.document?.id || (result.document.status === 'failed' && !result.job)) throw normalizeError(422, { message: result.document?.error || 'Индексация ранее завершилась ошибкой. Повторите её у документа.' });
        return { job: result.job, sourceId: result.source_id, documentId: result.document.id };
      });
    }}>
      <FormField id="bank-pdf" name="file" label="PDF-файл" hint="Не более 50 МиБ; повреждённые и зашифрованные PDF отклоняет сервер." errors={validation ? { file: [validation] } : {}}>{(props) =>
        <input {...props} type="file" accept=".pdf,application/pdf" disabled={work.busy} onChange={(event) => { setFile(event.target.files?.[0] || null); setValidation(''); }} />}</FormField>
      <button className="button primary" disabled={work.busy || list.loading || !file}>Загрузить и проиндексировать</button>
    </form>}
    {!list.error && <><MaterialJobStatus state={work} />{!work.busy && !work.error && work.success && work.accepted?.sourceId && <EvidenceLink id={work.accepted.sourceId} label="Основание загруженного PDF" />}</>}
    <AdminListStatus {...list} empty={!list.items.length}>
      <ul className="access-list" aria-label="Банковские документы">{list.items.map((document) => <li key={document.id}>
        <article className="panel access-card" aria-label={`Документ: ${document.filename}`}>
          <div className="access-heading"><h2>{document.filename}</h2><span className={`access-status ${document.status}`}>{processingLabels[document.status] || document.status}</span></div>
          <p>Дата документа: {document.document_date || 'Неизвестна'}. Страниц: {document.page_count}.</p>
          <p>Идентификатор документа: <code>{document.id}</code></p>
          {document.error && <p className="material-error" role="alert">Ошибка индексации: {document.error}</p>}
          {['queued', 'running'].includes(document.status) ? <p>Индексация выполняется. Обновите список или проверьте задание в разделе «Задания».</p> :
            <button className="button secondary" disabled={work.busy || list.loading} onClick={() => work.start('Индексация PDF', async (signal) => ({ job: await adminApi.reindex(document.id, signal), documentId: document.id }))}>{document.status === 'failed' ? 'Повторить индексацию' : 'Перестроить индекс'}</button>}
        </article></li>)}</ul>
    </AdminListStatus>
  </>;
}

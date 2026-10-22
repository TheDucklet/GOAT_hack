import { Link } from 'react-router-dom';
import { ErrorNotice } from '../../../shared/ui/ErrorNotice';
import type { useMaterialJob } from './useMaterialJob';

export const processingLabels: Record<string, string> = { queued: 'В очереди', running: 'Обрабатывается', done: 'Готово', failed: 'Ошибка', pending_ai: 'Ожидает анализа' };

export function MaterialJobStatus({ state }: { state: ReturnType<typeof useMaterialJob> }) {
  return <section className="material-job" aria-label="Текущая обработка" aria-busy={state.busy}>
    {state.busy && <p role="status">{state.label}: {state.job ? processingLabels[state.job.status] || state.job.status : 'отправляем запрос…'}</p>}
    {state.job && <p>Задание: <code>{state.job.id}</code> · {processingLabels[state.job.status] || state.job.status}. <Link to="/admin/jobs">Все задания</Link></p>}
    {state.success && <p className="success-notice" role="status">{state.success}</p>}
    {state.error != null && <><ErrorNotice error={state.error} retry={state.canResume ? state.resume : undefined} />
      <p>Автоматическая отправка не повторяется. {state.canResume ? 'Повторить — проверить то же задание.' : 'Проверьте список перед новым запуском. Для ошибки обработки используйте повтор у материала.'}</p></>}
  </section>;
}

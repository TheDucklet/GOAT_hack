import { ApiError } from '../../../shared/api/errors';
import { ErrorNotice } from '../../../shared/ui/ErrorNotice';
import { InsightNotice } from '../../../shared/ui/InsightNotice';
import { useAnalyticsSelection } from '../AnalyticsSelection';
import { InsightContent } from './InsightContent';
import { useInsight } from './useInsight';
import { InsightActions } from '../interactions/InsightActions';

function SelectedInsight({ hide }: { hide?: (insightId: string) => void }) {
  const { userId, companyId, event, insightId, rememberInsight } = useAnalyticsSelection();
  const state = useInsight(companyId, event!.event_id, insightId, rememberInsight);
  const budget = state.error instanceof ApiError && state.error.body.code === 'budget_exhausted';
  return <>
    <h3>{event!.title}</h3>
    {!state.insight && !state.loading && !state.error && <>
      <p>Подготовьте персональный анализ на основе источников и профиля компании.</p>
      <button className="button primary" onClick={state.build}>Подготовить анализ</button>
    </>}
    {state.loading && <p role="status">{state.job ? state.job.status === 'running' ? 'Готовим анализ…' : 'Анализ в очереди…' : 'Загружаем анализ…'}</p>}
    {state.error != null && <>
      {budget && <p>Дневной бюджет ИИ исчерпан. Сохранённые карточки остаются доступны; повторите подготовку после восстановления бюджета.</p>}
      <ErrorNotice error={state.error} retry={state.forbidden ? undefined : state.retry} />
    </>}
    {state.insight && <>
      <div className="insight-toolbar"><button className="button secondary" onClick={state.refresh}>Проверить актуальность</button>
        {state.insight.stale && <button className="button primary" onClick={state.build}>Обновить анализ</button>}
      </div>
      <InsightContent insight={state.insight} />
      {userId && <InsightActions key={state.insight.id} insight={state.insight} hide={hide ? () => hide(state.insight!.id) : undefined} />}
    </>}
  </>;
}

export function InsightPanel({ hide }: { hide?: (insightId: string) => void }) {
  const { event } = useAnalyticsSelection();
  return <section className="panel context-panel insight-panel" aria-labelledby="insight-heading" data-event-id={event?.event_id}>
    <h2 id="insight-heading">Анализ события</h2>
    <InsightNotice />
    {event ? <SelectedInsight key={event.event_id} hide={hide} /> : <p>Выберите событие в ленте, чтобы перейти к его аналитике.</p>}
  </section>;
}

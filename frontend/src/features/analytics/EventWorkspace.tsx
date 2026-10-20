import { useAnalyticsSelection } from './AnalyticsSelection';

export function InsightPanel() {
  const { event } = useAnalyticsSelection();
  return <section className="panel context-panel" aria-labelledby="insight-heading" data-event-id={event?.event_id}>
    <h2 id="insight-heading">Анализ события</h2>
    {event ? <><h3>{event.title}</h3><p>Подробная аналитическая карточка пока недоступна.</p></>
      : <p>Выберите событие в ленте, чтобы перейти к его аналитике.</p>}
  </section>;
}

export function ChatPanel() {
  const { event, chat } = useAnalyticsSelection();
  return <section className="panel context-panel" aria-labelledby="chat-heading" data-event-id={event?.event_id} data-chat-id={chat?.id}>
    <h2 id="chat-heading">Диалог по событию</h2>
    {event ? <><h3>{event.title}</h3><p>Диалог по выбранному событию пока недоступен.</p></>
      : <p>Выберите событие в ленте, чтобы задать вопрос о нём.</p>}
  </section>;
}

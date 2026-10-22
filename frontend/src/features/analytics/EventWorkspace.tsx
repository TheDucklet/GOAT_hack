import { useAnalyticsSelection } from './AnalyticsSelection';

export { InsightPanel } from './insights/InsightPanel';

export function ChatPanel() {
  const { event, chat } = useAnalyticsSelection();
  return <section className="panel context-panel" aria-labelledby="chat-heading" data-event-id={event?.event_id} data-chat-id={chat?.id}>
    <h2 id="chat-heading">Диалог по событию</h2>
    {event ? <><h3>{event.title}</h3><p>Диалог по выбранному событию пока недоступен.</p></>
      : <p>Выберите событие в ленте, чтобы задать вопрос о нём.</p>}
  </section>;
}

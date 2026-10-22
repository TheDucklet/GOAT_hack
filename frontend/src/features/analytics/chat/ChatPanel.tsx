import { ApiError } from '../../../shared/api/errors';
import { ErrorNotice } from '../../../shared/ui/ErrorNotice';
import { InsightNotice } from '../../../shared/ui/InsightNotice';
import { useAnalyticsSelection } from '../AnalyticsSelection';
import { ChatMessage } from './ChatMessage';
import { useChat } from './useChat';

function SelectedChat({ userId }: { userId: string }) {
  const { companyId, event, chat, setChat } = useAnalyticsSelection();
  const state = useChat(userId, companyId, event!.event_id, chat, setChat);
  const budget = state.error instanceof ApiError && state.error.body.code === 'budget_exhausted';
  return <>
    <h3>{event!.title}</h3>
    <p>Обсуждаем выбранное событие и компанию. Гипотезы и сценарии не являются установленными фактами.</p>
    {state.messages.length > 0 && <ol className="chat-history" aria-label="История диалога">{state.messages.map((message) => <ChatMessage key={message.id} message={message} />)}</ol>}
    {state.busy && <p role="status">{state.job ? state.job.status === 'running' ? 'Готовим ответ…' : 'Вопрос в очереди…' : state.sending ? 'Отправляем вопрос…' : 'Читаем диалог…'}</p>}
    {budget && <p className="insight-warning">Дневной бюджет ИИ исчерпан. Вопрос сохранён; повторите обработку после восстановления бюджета.</p>}
    {state.error != null && <ErrorNotice error={state.error} retry={state.retry} />}
    <div className="chat-prompts" aria-label="Уточнить анализ">{['Почему это важно нам?', 'Каких данных не хватает?'].map((question) =>
      <button className="button secondary" key={question} disabled={state.busy || state.forbidden} onClick={() => state.setText(question)}>{question}</button>)}</div>
    <form className="chat-form" onSubmit={(event) => { event.preventDefault(); state.send(); }}>
      <label htmlFor="chat-question">Вопрос по событию</label>
      <textarea id="chat-question" value={state.text} maxLength={10000} rows={4} disabled={state.busy} onChange={(event) => state.setText(event.target.value)} />
      <button className="button primary" disabled={state.busy || state.forbidden || !!state.error || !state.text.trim()}>Отправить вопрос</button>
    </form>
    {chat && <button className="text-button" disabled={state.busy} onClick={state.reload}>Обновить историю</button>}
  </>;
}

export function ChatPanel() {
  const { event, chat, userId } = useAnalyticsSelection();
  return <section className="panel context-panel chat-panel" aria-labelledby="chat-heading" data-event-id={event?.event_id} data-chat-id={chat?.id}>
    <h2 id="chat-heading">Диалог по событию</h2>
    <InsightNotice />
    {event && userId ? <SelectedChat key={event.event_id} userId={userId} /> : <p>Выберите событие в ленте, чтобы задать вопрос о нём.</p>}
  </section>;
}

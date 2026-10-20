import type { FeedItem } from '../../shared/api/types';

const factors: Record<string, string> = {
  industry: 'Отрасль', geo: 'Регион', product: 'Банковские продукты',
  relation: 'Деловые связи', focus: 'Ваши интересы',
};
const statuses: Record<string, string> = {
  pending_ai: 'Ожидает обработки',
  queued: 'Ожидает обработки', pending: 'Ожидает обработки', running: 'Обрабатывается',
  processing: 'Обрабатывается', ready: 'Обработано', done: 'Обработано', failed: 'Ошибка обработки',
};
const dateFormat = new Intl.DateTimeFormat('ru-RU', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Moscow',
});

export function sourceLink(value: unknown): URL | null {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url : null;
  } catch { return null; }
}

export function FeedEvent({ event, selected, onSelect }: { event: FeedItem; selected: boolean; onSelect(): void }) {
  const date = event.published_at ? new Date(event.published_at) : null;
  return <article className={`feed-event panel${selected ? ' selected' : ''}`}>
    <div className="feed-meta">
      {date && !Number.isNaN(date.getTime())
        ? <time dateTime={event.published_at!}>{dateFormat.format(date)} МСК</time>
        : <span>Дата не указана</span>}
      <span>{statuses[event.status] || event.status}</span>
    </div>
    <h3><button className="event-select" aria-pressed={selected} onClick={onSelect}>{event.title}</button></h3>
    <p className="event-summary">{event.summary || 'Краткое описание пока отсутствует.'}</p>
    <div className="event-sources"><strong>Источники</strong>
      {event.sources.length ? <ul>{event.sources.map((source, index) => {
        const url = sourceLink(source.url);
        const label = typeof source.title === 'string' ? source.title : url?.hostname || 'Источник без ссылки';
        return <li key={index}>{url ? <a href={url.href} target="_blank" rel="noopener noreferrer">{label} ↗</a> : <span>{label}</span>}</li>;
      })}</ul> : <span>Источники не указаны</span>}
    </div>
    <div className="event-reasons"><strong>Почему это важно</strong>
      {event.relevance_reasons.length ? <ul>{event.relevance_reasons.map((reason, index) => {
        const factor = typeof reason.factor === 'string' ? factors[reason.factor] || reason.factor : 'Релевантность';
        const topic = typeof reason.event_topic === 'string' ? reason.event_topic : typeof reason.description === 'string' ? reason.description : '';
        return <li key={index}>{factor}{topic && `: ${topic}`}</li>;
      })}</ul> : <span>Персональные причины не указаны</span>}
    </div>
    <span className="event-selection-label">{selected ? 'Событие выбрано' : 'Нажмите на заголовок, чтобы выбрать событие'}</span>
  </article>;
}

import type { FeedItem, FeedSnapshotItem } from '../../shared/api/types';
import { ClaimView } from './insights/ClaimView';
import { impactLabels, relevanceLabels } from './insights/labels';

const factors: Record<string, string> = {
  industry: 'Отрасль', geo: 'Регион', product: 'Банковские продукты',
  relation: 'Деловые связи', focus: 'Ваши интересы',
  impact: 'Сила влияния', relevance: 'Актуальность',
};
const statuses: Record<string, string> = {
  ready: 'Анализ подготовлен', not_requested: 'Персональный анализ ещё не подготовлен',
  failed: 'Не удалось подготовить анализ', deferred: 'Подготовка отложена', stale: 'Данные изменились — нужен новый анализ',
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

export function FeedEvent({ event, selected, onSelect, stale = false }: { event: FeedItem | FeedSnapshotItem; selected: boolean; onSelect(): void; stale?: boolean }) {
  const date = event.published_at ? new Date(event.published_at) : null;
  const preview = 'generation_status' in event ? event : null;
  const ready = !stale && preview?.generation_status === 'ready' && !!preview.insight_id;
  const status = stale ? 'stale' : preview?.generation_status || 'not_requested';
  return <article className={`feed-event panel${selected ? ' selected' : ''}`}>
    <div className="feed-meta">
      {date && !Number.isNaN(date.getTime())
        ? <time dateTime={event.published_at!}>{dateFormat.format(date)} МСК</time>
        : <span>Дата не указана</span>}
      <span className={status === 'stale' || status === 'failed' ? 'insight-warning' : undefined}>{statuses[status]}</span>
    </div>
    {ready ? <div className="feed-personal-preview">
      <strong>Что это значит для нас</strong>
      {preview.personalized_summary ? <div className="feed-personal-summary"><ClaimView claim={preview.personalized_summary} /></div>
        : <p>Недостаточно данных для персонального вывода.</p>}
      <div className="feed-impact"><strong>Влияние: {impactLabels[preview.impact_level]}</strong>
        <span>{relevanceLabels[preview.relevance_status]}</span></div>
      {preview.impact_reason && <ClaimView claim={preview.impact_reason} />}
      <strong>Почему это важно сейчас</strong>
      {preview.mechanism?.length ? preview.mechanism.map((claim) => <ClaimView key={claim.claim_id} claim={claim} />)
        : <p>Механизм не определён: недостаточно подтверждённых данных.</p>}
      <p>Горизонт: {preview.time_horizon?.label || 'Не определён'}.
        {preview.time_horizon?.starts_on && ` С ${preview.time_horizon.starts_on}.`}
        {preview.time_horizon?.ends_on && ` До ${preview.time_horizon.ends_on}.`}</p>
      {preview.relevance_reason && <ClaimView claim={preview.relevance_reason} />}
      {preview.valid_until && <p>Актуален до: {preview.valid_until}.</p>}
      {preview.review_after && <p>Перепроверить: {preview.review_after}.</p>}
      {!!preview.unknowns?.length && <div className="feed-unknowns"><strong>Что нужно уточнить</strong><ul>{preview.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul></div>}
    </div> : <p className="muted">{status === 'stale' ? 'Предыдущий персональный вывод скрыт. Обновите ленту, чтобы учесть изменения.' : 'Готового персонального вывода пока нет. Текст новости ниже — источник, а не вывод о вашей компании.'}</p>}
    <div className="feed-news-basis"><strong>Новость-основание</strong>
    <h3><button className="event-select" aria-pressed={selected} onClick={onSelect}>{event.title}</button></h3>
    <details open={!preview || undefined}><summary>Исходный текст новости</summary><p className="event-summary">{event.summary || 'Краткое описание пока отсутствует.'}</p></details>
    </div>
    <div className="event-sources"><strong>Источники</strong>
      {event.sources.length ? <ul>{event.sources.map((source, index) => {
        const url = sourceLink(source.url);
        const label = typeof source.title === 'string' ? source.title : url?.hostname || 'Источник без ссылки';
        return <li key={index}>{url ? <a href={url.href} target="_blank" rel="noopener noreferrer">{label} ↗</a> : <span>{label}</span>}</li>;
      })}</ul> : <span>Источники не указаны</span>}
    </div>
    <div className="event-reasons"><strong>Контекст отбора новости</strong>
      {event.relevance_reasons.length ? <ul>{event.relevance_reasons.map((reason, index) => {
        const factor = typeof reason.factor === 'string' ? factors[reason.factor] || 'Релевантность' : 'Релевантность';
        const topic = typeof reason.event_topic === 'string' ? reason.event_topic : typeof reason.description === 'string' ? reason.description : '';
        return <li key={index}>{factor}{topic && `: ${topic}`}</li>;
      })}</ul> : <span>Персональные причины не указаны</span>}
    </div>
    <span className="event-selection-label">{selected ? 'Событие выбрано' : 'Нажмите на заголовок, чтобы выбрать событие'}</span>
  </article>;
}

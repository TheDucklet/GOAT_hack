import { useEffect, useId, useState } from 'react';
import { evidenceApi, externalSourceUrl } from '../api/evidence';
import { normalizeError } from '../api/errors';
import type { Evidence } from '../api/types';
import { ErrorNotice } from './ErrorNotice';

function text(value: unknown) {
  return value === undefined || value === null ? 'Не указано' : typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function SourceDetails({ source }: { source: Evidence }) {
  const locator = source.locator;
  const url = externalSourceUrl(locator.url);
  const feature = locator.value && typeof locator.value === 'object' ? locator.value as Record<string, unknown> : null;
  const page = typeof locator.page === 'number' && Number.isSafeInteger(locator.page) && locator.page > 0 ? locator.page : null;
  return <div className="evidence-details">
    <strong>{source.kind === 'bank' ? 'Банковский материал' : source.kind === 'company' ? 'Наблюдаемый признак профиля' : 'Новостной первоисточник'}</strong>
    {source.kind === 'bank' && <>
      <p>Дата документа: {text(locator.document_date)}. {page ? `Страница ${page}.` : 'Страница не указана.'}</p>
      <p>{({ current: 'Материал прошёл проверку давности', historical: 'Исторический материал — не текущая позиция банка', undated: 'Дата материала неизвестна', applicability_unknown: 'Применимость материала не подтверждена', period_expired: 'Период применения материала истёк', source_changed: 'Версия источника изменилась' } as Record<string, string>)[String(locator.temporal_status)] || 'Актуальность материала не подтверждена'}{locator.evaluated_on ? ` · проверено ${text(locator.evaluated_on)}` : ''}</p>
      {page && locator.temporal_status !== 'source_changed' && <a href={evidenceApi.fileUrl(source.id, page)} target="_blank" rel="noopener noreferrer">Открыть защищённый PDF · страница {page} ↗</a>}
    </>}
    {source.kind === 'news' && <>
      <p>Дата публикации: {text(locator.published_at)}</p>
      {url ? <a href={url.href} target="_blank" rel="noopener noreferrer">Первоисточник · {url.hostname} ↗</a> : <p>Безопасная ссылка на публикацию не указана.</p>}
    </>}
    {source.kind === 'company' && <>
      <p>Поле: <code>{text(locator.feature_path)}</code></p>
      <p>Значение: {text(feature && 'value' in feature ? feature.value : locator.value)}</p>
      {feature?.quality != null && <p>Качество признака: {text(feature.quality)}</p>}
      {locator.stale === true && <p className="insight-warning">Признак из прежней версии профиля. Текущее значение могло измениться.</p>}
    </>}
    <blockquote>{source.excerpt || 'Фрагмент не указан.'}</blockquote>
    <small>Версия источника: {source.version}</small>
  </div>;
}

// Every source is resolved through the authorized API, never from a model-supplied URL.
export function EvidenceLink({ id, label = 'Основание' }: { id: string; label?: string }) {
  const regionId = useId();
  const [open, setOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [source, setSource] = useState<Evidence | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSource(null); setError(null);
    void evidenceApi.source(id, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.id !== id || !['bank', 'news', 'company'].includes(result.kind) || !result.locator || typeof result.locator !== 'object') {
        throw normalizeError(502, { message: 'Некорректное основание в ответе сервера.' });
      }
      setSource(result);
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason); });
    return () => controller.abort();
  }, [id, open, attempt]);
  return <div className="evidence-link">
    <button className="text-button" type="button" aria-expanded={open} aria-controls={regionId} onClick={() => setOpen((value) => !value)}>{label}</button>
    {open && <div id={regionId} role="region" aria-label={label}>
      {error ? <ErrorNotice error={error} retry={() => setAttempt((value) => value + 1)} /> : source?.id === id ? <SourceDetails source={source} /> : <p role="status">Проверяем доступ к источнику…</p>}
    </div>}
  </div>;
}

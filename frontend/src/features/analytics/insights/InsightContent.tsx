import { isInsightV2 } from '../../../shared/api/insight-contract';
import type { Claim, Insight, InsightResultV2 } from '../../../shared/api/types';
import { ClaimView, EvidenceReferences } from './ClaimView';

import { impactLabels as impact, relevanceLabels as relevance } from './labels';
const bankStatus = {
  current: 'Банковский материал с подтверждённой датой', historical: 'Исторический банковский материал — не текущая позиция банка',
  missing: 'Позиция банка отсутствует', undated: 'Дата банковского материала неизвестна',
};

function Claims({ title, claims = [], legacyLabel }: { title: string; claims?: Claim[] | null; legacyLabel?: string }) {
  return <section className="insight-section" aria-label={title}><h3>{title}</h3>
    {claims?.length ? claims.map((claim) => <ClaimView key={claim.claim_id} claim={claim} legacyLabel={legacyLabel} />) : <p className="muted">Не указано.</p>}
  </section>;
}

function Impact({ result }: { result: InsightResultV2 }) {
  return <>
    <section className="insight-section" aria-label="Что это значит для компании"><h3>Что это значит для компании</h3>
      {result.personalized_summary ? <ClaimView claim={result.personalized_summary} /> : <p>Недостаточно данных для персонального вывода.</p>}
    </section>
    <section className="insight-section" aria-label="Влияние"><h3>Влияние: {impact[result.impact_level] || impact.undetermined}</h3>
      {result.impact_reason && <ClaimView claim={result.impact_reason} />}
      <p>Горизонт: {result.time_horizon?.label || 'Не определён'}.</p>
      <p>Начало: {result.time_horizon?.starts_on || 'Не установлено'}; окончание: {result.time_horizon?.ends_on || 'Не установлено'}.</p>
    </section>
    <Claims title="Механизм влияния" claims={result.mechanism} />
    <Claims title="Предпосылки" claims={result.assumptions} />
    <section className="insight-section" aria-label="Актуальность"><h3>{relevance[result.relevance_status] || relevance.undetermined}</h3>
      {result.relevance_reason && <ClaimView claim={result.relevance_reason} />}
      <p>Действует с: {result.valid_from || 'Не установлено'}; до: {result.valid_until || 'Окончание не установлено'}.</p>
      <p>Перепроверить: {result.review_after || 'Дата не установлена'}.</p>
    </section>
  </>;
}

export function InsightContent({ insight }: { insight: Insight }) {
  const result = insight.result;
  const v2 = isInsightV2(result) ? result : null;
  const bank = result.bank_view;
  const hasBank = !!bank?.length;
  return <div className="insight-content">
    {insight.stale && <p className="insight-warning" role="status">Карточка устарела: входные данные изменились. Обновите анализ перед использованием.</p>}
    {!v2 && <p className="muted">Карточка v1. Оценка влияния, актуальность и типы выводов не определены.</p>}
    {v2 && <Impact result={v2} />}
    <Claims title="Факты из источников" claims={result.facts} legacyLabel="Факт из источника · карточка v1" />
    <section className="insight-section" aria-label="Банковский материал"><h3>Банковский материал</h3>
      <p className={(!hasBank || v2?.bank_view_context?.status !== 'current') ? 'insight-warning' : undefined}>
        {!hasBank ? bankStatus.missing : v2 ? bankStatus[v2.bank_view_context?.status] || bankStatus.undated : 'Статус и дата банковской позиции не указаны в карточке v1.'}
      </p>
      {v2?.bank_view_context?.document_dates?.map((date) => <p key={date}>Дата документа: <time dateTime={date}>{date}</time></p>)}
      {!hasBank && <p>Внешний анализ приведён ниже. Он не является позицией банка.</p>}
      {bank?.map((claim) => <ClaimView key={claim.claim_id} claim={claim} legacyLabel="Банковский источник · карточка v1" />)}
      {hasBank && <small>Точная страница и дата доступны в основаниях утверждения.</small>}
    </section>
    <Claims title="Интерпретация ИИ" claims={result.ai_interpretation} />
    <Claims title="Риски" claims={result.risks} />
    <Claims title="Возможности" claims={result.opportunities} />
    <Claims title="Возможные действия" claims={result.actions} />
    <section className="insight-section" aria-label="Что неизвестно"><h3>Что неизвестно</h3>
      {result.unknowns?.length ? <ul>{result.unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>Ограничения не указаны. Это не подтверждение полноты данных.</p>}
    </section>
    <details><summary>Все основания и версия карточки</summary>
      <EvidenceReferences refs={result.evidence_refs} />
      <p>Карточка: {insight.id}</p><p>Трасса: {result.trace_id || 'Не указана'}</p>
    </details>
  </div>;
}

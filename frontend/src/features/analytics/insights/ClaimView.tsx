import type { Claim, InsightResultV2 } from '../../../shared/api/types';
import { EvidenceLink } from '../../../shared/ui/EvidenceLink';

type Statement = InsightResultV2['mechanism'][number];
const types = { fact: 'Факт из источника', hypothesis: 'Гипотеза', scenario: 'Сценарий' };

export function EvidenceReferences({ refs = [] }: { refs?: string[] }) {
  return refs.length ? <div className="claim-evidence" aria-label="Основания утверждения">{[...new Set(refs)].map((id, index) =>
    <EvidenceLink key={id} id={id} label={`Основание ${index + 1}`} />)}</div> : <small>Основания не указаны.</small>;
}

export function ClaimView({ claim, legacyLabel = 'Вывод ИИ · тип утверждения не указан' }: { claim: Claim | Statement; legacyLabel?: string }) {
  const statement = 'statement_type' in claim ? claim : null;
  const scenario = statement?.quantitative_scenario;
  return <div className="insight-claim" data-statement-type={statement?.statement_type || 'unspecified'}>
    <span className="claim-kind">{statement ? types[statement.statement_type] || 'Тип утверждения не указан' : legacyLabel}</span>
    <p>{claim.text}</p>
    {scenario && <div className="quantitative-scenario">
      <strong>Условный расчёт, не прогноз</strong>
      <ul>{scenario.inputs.map((input) => <li key={input.name}>{input.name}: {input.value} {input.unit}; период: {input.period}
        <EvidenceReferences refs={input.input_refs} /></li>)}</ul>
      <p>Формула: <code>{scenario.formula}</code></p>
      <p>Диапазон: {scenario.result_range.lower}–{scenario.result_range.upper} {scenario.unit}; период: {scenario.period}</p>
      <p>Предпосылки расчёта:</p><ul>{scenario.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </div>}
    <EvidenceReferences refs={claim.evidence_refs} />
  </div>;
}

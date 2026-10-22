import type { Message } from '../../../shared/api/types';
import { EvidenceReferences } from '../insights/ClaimView';

function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []; }

export function ChatMessage({ message }: { message: Message }) {
  const result = message.result;
  const assumptions = strings(result?.assumptions);
  const unknowns = strings(result?.unknowns);
  return <li className={`chat-message chat-${message.role}`}>
    <strong>{message.role === 'user' ? 'Ваш вопрос' : 'Ответ ИИ · выводы требуют проверки'}</strong>
    <p>{message.text}</p>
    {message.role === 'assistant' && <>
      <section aria-label="Предпосылки ответа"><h4>Предпосылки</h4>
        {assumptions.length ? <ul>{assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>Отдельные предпосылки в ответе не указаны. Проверьте применимость вывода по основаниям.</p>}
      </section>
      <section aria-label="Ограничения ответа"><h4>Что неизвестно</h4>
        {unknowns.length ? <ul>{unknowns.map((item, index) => <li key={index}>{item}</li>)}</ul> : <p>Ограничения не указаны; это не подтверждение полноты данных.</p>}
      </section>
      <EvidenceReferences refs={strings(result?.evidence_refs)} />
    </>}
  </li>;
}

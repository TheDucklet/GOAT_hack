import { useEffect, useId, useState, type FormEvent } from 'react';
import { ApiError } from '../api/errors';
import type { Membership, MembershipProfile } from '../api/types';
import { ErrorNotice } from './ErrorNotice';

interface Props {
  membership?: Membership;
  label: string;
  save(profile: MembershipProfile, companyId: string): Promise<Membership>;
  onSaved(membership: Membership): void;
}

export function MembershipForm({ membership, label, save, onSaved }: Props) {
  const id = useId();
  const [companyId, setCompanyId] = useState('');
  const [position, setPosition] = useState(membership?.position_text || '');
  const [interests, setInterests] = useState(membership?.interests.join('\n') || '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});
  const [saved, setSaved] = useState(false);
  const storedPosition = membership?.position_text || '';
  const storedInterests = membership?.interests.join('\n') || '';
  useEffect(() => { setPosition(storedPosition); setInterests(storedInterests); }, [storedPosition, storedInterests]);

  const messages = (field: string) => Object.entries(fields)
    .filter(([key]) => key === field || key.startsWith(`${field}.`)).flatMap(([, values]) => values);
  const changed = (field: string) => {
    setSaved(false);
    setFields((current) => Object.fromEntries(Object.entries(current).filter(([key]) => key !== field && !key.startsWith(`${field}.`))));
  };
  const fieldProps = (field: string) => ({
    id: `${id}-${field}`, name: field, 'aria-invalid': messages(field).length > 0,
    'aria-describedby': `${id}-${field}-hint${messages(field).length ? ` ${id}-${field}-error` : ''}`,
  });
  const fieldError = (field: string) => messages(field).length > 0 && <p id={`${id}-${field}-error`} className="field-error">{messages(field).join(' ')}</p>;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError(null); setFields({}); setSaved(false);
    try {
      const result = await save({ position_text: position, interests: interests.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) }, companyId.trim());
      onSaved(result);
      setSaved(true);
      if (!membership) { setCompanyId(''); setPosition(''); setInterests(''); }
      else { setPosition(result.position_text); setInterests(result.interests.join('\n')); }
    } catch (reason) {
      setError(reason);
      if (reason instanceof ApiError) setFields(!membership && [404, 409].includes(reason.status)
        ? { company_id: [reason.message] } : reason.fieldErrors);
    } finally { setPending(false); }
  }

  return <form onSubmit={submit} noValidate aria-label={label}>
    {error != null && <ErrorNotice error={error} showFields={false} />}
    {saved && <p className="success-notice" role="status">{membership ? 'Профиль сохранён.' : 'Заявка отправлена. Ожидайте подтверждения администратора.'}</p>}
    <fieldset disabled={pending}>
      {!membership && <div className="field"><label htmlFor={`${id}-company_id`}>Идентификатор компании</label>
        <input {...fieldProps('company_id')} value={companyId} onChange={(event) => { setCompanyId(event.target.value); changed('company_id'); }} required />
        <p id={`${id}-company_id-hint`} className="field-hint">Получите идентификатор у администратора компании.</p>{fieldError('company_id')}
      </div>}
      <div className="field"><label htmlFor={`${id}-position_text`}>Должность</label>
        <textarea {...fieldProps('position_text')} value={position} rows={2} onChange={(event) => { setPosition(event.target.value); changed('position_text'); }} />
        <p id={`${id}-position_text-hint`} className="field-hint">Любая должность, до 1000 символов. Она помогает настроить аналитику и не меняет права доступа.</p>{fieldError('position_text')}
      </div>
      <div className="field"><label htmlFor={`${id}-interests`}>Интересы</label>
        <textarea {...fieldProps('interests')} value={interests} rows={3} onChange={(event) => { setInterests(event.target.value); changed('interests'); }} />
        <p id={`${id}-interests-hint`} className="field-hint">По одной теме на строку, до 30 тем. Например: налоги или международные расчёты.</p>{fieldError('interests')}
      </div>
      <button className="button primary" type="submit">{pending ? 'Сохраняем…' : membership ? 'Сохранить профиль' : 'Отправить заявку'}</button>
    </fieldset>
  </form>;
}

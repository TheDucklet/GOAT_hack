import { FormField, clearFieldErrors } from '../../shared/ui/FormField';
import { useEffect, useId, useState, type FormEvent } from 'react';
import { ApiError } from '../../shared/api/errors';
import type { Membership, MembershipProfile } from '../../shared/api/types';
import { ErrorNotice } from '../../shared/ui/ErrorNotice';

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

  const changed = (field: string) => {
    setSaved(false);
    setFields((current) => clearFieldErrors(current, field));
  };

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
      {!membership && <FormField id={`${id}-company_id`} name="company_id" label="Идентификатор компании" hint="Получите идентификатор у администратора компании." errors={fields}>
        {(props) => <input {...props} value={companyId} onChange={(event) => { setCompanyId(event.target.value); changed('company_id'); }} required />}
      </FormField>}
      <FormField id={`${id}-position_text`} name="position_text" label="Должность" hint="Любая должность, до 1000 символов. Она помогает настроить аналитику и не меняет права доступа." errors={fields}>
        {(props) => <textarea {...props} value={position} rows={2} onChange={(event) => { setPosition(event.target.value); changed('position_text'); }} />}
      </FormField>
      <FormField id={`${id}-interests`} name="interests" label="Интересы" hint="По одной теме на строку, до 30 тем. Например: налоги или международные расчёты." errors={fields}>
        {(props) => <textarea {...props} value={interests} rows={3} onChange={(event) => { setInterests(event.target.value); changed('interests'); }} />}
      </FormField>
      <button className="button primary" type="submit">{pending ? 'Сохраняем…' : membership ? 'Сохранить профиль' : 'Отправить заявку'}</button>
    </fieldset>
  </form>;
}

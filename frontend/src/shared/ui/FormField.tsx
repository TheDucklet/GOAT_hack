import type { ReactNode } from 'react';

export type FieldErrors = Record<string, string[]>;
export function clearFieldErrors(errors: FieldErrors, name: string): FieldErrors {
  return Object.fromEntries(Object.entries(errors).filter(([key]) => key !== name && !key.startsWith(`${name}.`)));
}
interface ControlProps {
  id: string;
  name: string;
  'aria-invalid': boolean;
  'aria-describedby': string | undefined;
}
interface Props {
  id: string;
  name: string;
  label: string;
  hint?: string;
  errors: FieldErrors;
  children(props: ControlProps): ReactNode;
}

export function FormField({ id, name, label, hint, errors, children }: Props) {
  const messages = Object.entries(errors).filter(([key]) => key === name || key.startsWith(`${name}.`)).flatMap(([, values]) => values);
  const describedBy = [hint ? `${id}-hint` : '', messages.length ? `${id}-error` : ''].filter(Boolean).join(' ');
  return <div className="field"><label htmlFor={id}>{label}</label>
    {children({ id, name, 'aria-invalid': messages.length > 0, 'aria-describedby': describedBy || undefined })}
    {hint && <p id={`${id}-hint`} className="field-hint">{hint}</p>}
    {messages.length > 0 && <p id={`${id}-error`} className="field-error">{messages.join(' ')}</p>}
  </div>;
}

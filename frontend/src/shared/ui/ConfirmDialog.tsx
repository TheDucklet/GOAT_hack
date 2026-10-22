import { useEffect, useId, useRef } from 'react';
import { ErrorNotice } from './ErrorNotice';

export function ConfirmDialog({ title, description, busy, error, confirm, cancel }: {
  title: string; description: string; busy: boolean; error: unknown; confirm(): void; cancel(): void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const previous = document.activeElement;
    ref.current?.showModal();
    return () => { ref.current?.close(); if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return <dialog className="confirm-dialog" ref={ref} aria-labelledby={titleId} aria-describedby={descriptionId}
    onCancel={(event) => { event.preventDefault(); if (!busy) cancel(); }}>
    <h2 id={titleId}>{title}</h2><p id={descriptionId}>{description}</p>
    {error != null && <><ErrorNotice error={error} /><p>Изменение не подтверждено. Повторная отправка выполняется только по вашему нажатию.</p></>}
    <div className="confirm-actions"><button className="button secondary" autoFocus disabled={busy} onClick={cancel}>Отмена</button>
      <button className="button primary" disabled={busy} onClick={confirm}>{busy ? 'Сохраняем…' : error ? 'Повторить изменение' : 'Подтвердить изменение'}</button></div>
  </dialog>;
}

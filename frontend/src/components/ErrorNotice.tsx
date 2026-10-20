import { ApiError, errorMessage } from '../api/errors';

export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  return <div className="error-notice" role="alert">
    <strong>{errorMessage(error)}</strong>
    {error instanceof ApiError && error.body.request_id && <small>Код обращения: {error.body.request_id}</small>}
    {error instanceof ApiError && error.status === 422 && Object.keys(error.fieldErrors).length > 0 &&
      <ul>{Object.entries(error.fieldErrors).map(([field, messages]) => <li key={field}>{field}: {messages.join(' ')}</li>)}</ul>}
    {retry && <button className="button secondary" onClick={retry}>Повторить</button>}
  </div>;
}

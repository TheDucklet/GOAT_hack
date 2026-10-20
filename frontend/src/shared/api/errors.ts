import type { ApiErrorBody } from './types';

export class ApiError extends Error {
  constructor(public status: number, public body: ApiErrorBody) {
    super(body.message);
    this.name = 'ApiError';
  }

  get fieldErrors(): Record<string, string[]> {
    const fields: Record<string, string[]> = {};
    for (const issue of this.body.field_errors || []) {
      const loc = Array.isArray(issue.loc) ? issue.loc.filter((part) => !['body', 'query', 'path'].includes(String(part))) : [];
      const field = loc.length ? loc.join('.') : '_form';
      const message = typeof issue.message === 'string' ? issue.message : 'Проверьте поле.';
      (fields[field] ||= []).push(message);
    }
    return fields;
  }
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Не удалось выполнить запрос. Повторите попытку.';
  if (error.status === 401) return error.body.code === 'invalid_credentials' ? error.message : 'Сессия завершена. Войдите снова.';
  if (error.status === 403) return 'Нет доступа';
  if (error.status === 422) return 'Проверьте заполненные поля.';
  if (error.status === 503 || error.status === 0) return 'Сервис временно недоступен. Повторите попытку.';
  return error.message;
}

export function normalizeError(status: number, value: unknown): ApiError {
  const data = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const fields = Array.isArray(data.field_errors)
    ? data.field_errors.filter((issue): issue is Record<string, unknown> => !!issue && typeof issue === 'object' && !Array.isArray(issue))
    : [];
  return new ApiError(status, {
    code: typeof data.code === 'string' ? data.code : 'request_failed',
    message: typeof data.message === 'string' ? data.message : 'Не удалось выполнить запрос.',
    request_id: typeof data.request_id === 'string' ? data.request_id : '',
    field_errors: fields,
  });
}

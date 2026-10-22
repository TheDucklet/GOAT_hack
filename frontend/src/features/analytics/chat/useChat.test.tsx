import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HttpClient } from '../../../shared/api/http';
import { normalizeError } from '../../../shared/api/errors';
import type { ChatState, Job, Message } from '../../../shared/api/types';

vi.mock('../../../shared/api/index', () => ({ http: new HttpClient('/api', async () => { throw new Error('Unexpected HTTP'); }) }));
import { analyticsApi } from '../api';
import { jobsApi } from '../../../shared/api/jobs';
import { useChat } from './useChat';

const chat: ChatState = { id: 'chat-a', company_id: 'company-a', event_id: 'event-a', event_title: 'Событие' };
const user: Message = { id: 'question', chat_id: chat.id, sequence: 1, role: 'user', text: 'Почему это важно нам?', result: null, created_at: '2026-10-22T12:00:00Z' };
const answer: Message = { ...user, id: 'answer', sequence: 2, role: 'assistant', text: 'Условный ответ', result: { evidence_refs: [], unknowns: ['Неизвестна сумма'] } };
const queued: Job = { id: 'job-a', status: 'queued', attempts: 0 };
const done: Job = { ...queued, status: 'done', result: { chat_id: chat.id, message_id: answer.id } };
let scope = 0;
function open(initial: ChatState | null = null, userId = `user-${++scope}`) {
  const onChat = vi.fn();
  return { ...renderHook(({ companyId, eventId }) => useChat(userId, companyId, eventId, initial, onChat), { initialProps: { companyId: chat.company_id, eventId: chat.event_id } }), onChat };
}
beforeEach(() => {
  vi.spyOn(analyticsApi, 'createChat').mockResolvedValue(chat);
  vi.spyOn(analyticsApi, 'chat').mockResolvedValue(chat);
  vi.spyOn(analyticsApi, 'messages').mockResolvedValue([user, answer]);
  vi.spyOn(analyticsApi, 'sendMessage').mockResolvedValue(done);
  vi.spyOn(jobsApi, 'job').mockResolvedValue(done);
});
afterEach(() => { vi.useRealTimers(); });

describe('R06 contextual chat state', () => {
  it('creates one contextual chat and submits a question once even under repeated clicks', async () => {
    const { result, onChat } = open();
    await waitFor(() => expect(result.current.busy).toBe(false));
    act(() => result.current.setText(user.text));
    act(() => { result.current.send(); result.current.send(); });
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(analyticsApi.createChat).toHaveBeenCalledExactlyOnceWith('company-a', 'event-a', expect.any(AbortSignal));
    expect(analyticsApi.sendMessage).toHaveBeenCalledExactlyOnceWith('chat-a', user.text, expect.any(AbortSignal), expect.any(String), false);
    expect(onChat).toHaveBeenCalledWith(chat);
    expect(result.current.text).toBe('');
  });

  it('restores authorized server history before showing it and does not submit on reload', async () => {
    const { result } = open(chat);
    await waitFor(() => expect(result.current.messages).toHaveLength(2));
    expect(analyticsApi.chat).toHaveBeenCalledWith(chat.id, expect.any(AbortSignal));
    expect(analyticsApi.createChat).not.toHaveBeenCalled(); expect(analyticsApi.sendMessage).not.toHaveBeenCalled();
  });

  it('retains the question after a lost POST response and reuses its idempotency key on manual retry', async () => {
    vi.mocked(analyticsApi.sendMessage).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValue(done);
    const { result } = open();
    act(() => result.current.setText(user.text)); act(() => result.current.send());
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.text).toBe(user.text); expect(analyticsApi.sendMessage).toHaveBeenCalledTimes(1);
    const key = vi.mocked(analyticsApi.sendMessage).mock.calls[0]![3];
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.text).toBe(''));
    expect(vi.mocked(analyticsApi.sendMessage).mock.calls[1]![3]).toBe(key);
    expect(analyticsApi.createChat).toHaveBeenCalledTimes(1);
  });

  it('preserves a budget-failed question and explicitly retries processing with the same key', async () => {
    vi.mocked(analyticsApi.sendMessage).mockResolvedValueOnce({ ...queued, status: 'failed', error: { code: 'budget_exhausted', message: 'Budget exhausted' } }).mockResolvedValue(done);
    const { result } = open();
    act(() => result.current.setText(user.text)); act(() => result.current.send());
    await waitFor(() => expect(result.current.error).toMatchObject({ body: { code: 'budget_exhausted' } }));
    expect(result.current.text).toBe(user.text);
    const key = vi.mocked(analyticsApi.sendMessage).mock.calls[0]![3];
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.error).toBeNull());
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(vi.mocked(analyticsApi.sendMessage).mock.calls[1]!.slice(3)).toEqual([key, true]);
  });

  it('resumes read-only polling after a network error without resubmitting the question', async () => {
    vi.useFakeTimers();
    vi.mocked(analyticsApi.sendMessage).mockResolvedValue(queued);
    vi.mocked(jobsApi.job).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValue(done);
    const { result } = open();
    await act(async () => {});
    act(() => result.current.setText(user.text)); act(() => result.current.send());
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(result.current.error).toBeTruthy(); expect(result.current.text).toBe(user.text);
    act(() => result.current.retry()); await act(async () => {});
    expect(result.current.messages).toHaveLength(2);
    expect(analyticsApi.sendMessage).toHaveBeenCalledTimes(1); expect(jobsApi.job).toHaveBeenCalledTimes(2);
  });

  it('restores an in-flight job on reload and polls without creating a second question', async () => {
    vi.useFakeTimers();
    vi.mocked(analyticsApi.chat).mockResolvedValue({ ...chat, last_job: queued, last_message_id: user.id, last_client_message_id: 'existing-question' });
    const { result } = open(chat);
    await act(async () => {});
    expect(result.current.text).toBe(user.text);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(result.current.text).toBe(''); expect(result.current.messages).toHaveLength(2);
    expect(analyticsApi.sendMessage).not.toHaveBeenCalled();
  });

  it('rejects a foreign chat response before fetching any history or sending a question', async () => {
    vi.mocked(analyticsApi.chat).mockResolvedValue({ ...chat, company_id: 'foreign' });
    const { result } = open(chat);
    await waitFor(() => expect(result.current.forbidden).toBe(true));
    expect(analyticsApi.messages).not.toHaveBeenCalled(); expect(result.current.messages).toEqual([]);
  });

  it('rejects messages from another chat and keeps the current history empty', async () => {
    vi.mocked(analyticsApi.messages).mockResolvedValue([{ ...answer, chat_id: 'foreign' }]);
    const { result } = open(chat);
    await waitFor(() => expect(result.current.forbidden).toBe(true));
    expect(result.current.messages).toEqual([]);
  });

  it.each([401, 403])('keeps the question on %s without fabricating an answer or an automatic resend', async (status) => {
    vi.mocked(analyticsApi.sendMessage).mockRejectedValue(normalizeError(status, {}));
    const { result } = open();
    act(() => result.current.setText(user.text)); act(() => result.current.send());
    await waitFor(() => expect(result.current.forbidden).toBe(true));
    expect(result.current.text).toBe(user.text); expect(result.current.messages).toEqual([]);
    expect(analyticsApi.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('retains a draft through login-route unmount for the same user while isolating another account', async () => {
    const first = open(null, 'draft-owner');
    act(() => first.result.current.setText('Сохранённый вопрос'));
    first.unmount();
    const restored = open(null, 'draft-owner');
    expect(restored.result.current.text).toBe('Сохранённый вопрос'); restored.unmount();
    const other = open(null, 'another-user');
    expect(other.result.current.text).toBe('');
    expect(sessionStorage.length).toBe(0); expect(localStorage.length).toBe(0);
  });

  it('aborts pending work on unmount and ignores a late accepted job', async () => {
    let resolve!: (value: Job) => void;
    vi.mocked(analyticsApi.sendMessage).mockReturnValue(new Promise((done) => { resolve = done; }));
    const view = open();
    act(() => view.result.current.setText(user.text)); act(() => view.result.current.send());
    await waitFor(() => expect(analyticsApi.sendMessage).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(analyticsApi.sendMessage).mock.calls[0]![2]!;
    view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => resolve(done));
    expect(jobsApi.job).not.toHaveBeenCalled();
  });
});

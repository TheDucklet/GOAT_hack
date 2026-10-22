import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, normalizeError } from '../../../shared/api/errors';
import { JobFailure, jobsApi, waitForJob } from '../../../shared/api/jobs';
import type { Chat, ChatState, Job, Message } from '../../../shared/api/types';
import { analyticsApi } from '../api';
import { draftScope, readDraft, saveDraft, type ChatDraft } from './drafts';

function validateChat(chat: Chat, companyId: string, eventId: string) {
  if (!chat || typeof chat.id !== 'string' || chat.company_id !== companyId || chat.event_id !== eventId) {
    throw normalizeError(403, { code: 'wrong_chat_context', message: 'Диалог не относится к выбранной компании и событию.' });
  }
  return chat;
}

async function history(chatId: string, signal: AbortSignal) {
  const rows: Message[] = [];
  for (let offset = 0; ; offset += 100) {
    signal.throwIfAborted();
    const page = await analyticsApi.messages(chatId, signal, 100, offset);
    if (page.some((message) => message.chat_id !== chatId)) throw normalizeError(403, { message: 'Получены сообщения другого диалога.' });
    rows.push(...page);
    if (page.length < 100) return [...new Map(rows.map((message) => [message.id, message])).values()].sort((a, b) => a.sequence - b.sequence);
  }
}

type Mode = 'restore' | 'submit' | 'poll' | 'failed';

export function useChat(userId: string, companyId: string, eventId: string, initialChat: Chat | null, onChat: (chat: Chat) => void) {
  const scope = draftScope(userId, companyId, eventId);
  const draft = useRef<ChatDraft>(readDraft(scope));
  const chat = useRef<Chat | null>(initialChat);
  const pending = useRef<Job | null>(null);
  const submittedKey = useRef<string | null>(null);
  const mode = useRef<Mode>('restore');
  const active = useRef<AbortController | null>(null);
  const [text, setText] = useState(draft.current.text);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sending, setSending] = useState(false);

  const updateDraft = useCallback((next: ChatDraft) => { draft.current = next; saveDraft(scope, next); setText(next.text); }, [scope]);
  const run = useCallback((operation: Mode) => {
    if (active.current && !active.current.signal.aborted) return;
    if ((operation === 'submit' || operation === 'failed') && !draft.current.text.trim()) return;
    const controller = new AbortController();
    active.current = controller;
    const signal = controller.signal;
    setBusy(true); setError(null); mode.current = operation;
    setJob(null); setSending(operation === 'submit' || operation === 'failed');
    void (async () => {
      if (operation === 'restore') {
        if (!chat.current) return;
        const state: ChatState = await analyticsApi.chat(chat.current.id, signal);
        signal.throwIfAborted(); validateChat(state, companyId, eventId);
        const rows = await history(state.id, signal);
        signal.throwIfAborted(); setMessages(rows); onChat(state);
        const last = rows.find((item) => item.id === state.last_message_id);
        if (state.last_job && state.last_job.status !== 'done') {
          if (state.last_job.status === 'failed' && draft.current.text && draft.current.key !== state.last_client_message_id) return;
          pending.current = state.last_job;
          if (!draft.current.text && last?.role === 'user') updateDraft({ text: last.text, key: state.last_client_message_id || crypto.randomUUID() });
          submittedKey.current = state.last_client_message_id || draft.current.key;
          mode.current = 'poll';
        } else {
          if (state.last_job?.status === 'done' && state.last_client_message_id === draft.current.key) updateDraft({ text: '', key: crypto.randomUUID() });
          pending.current = null; return;
        }
      }
      if (operation === 'submit' || operation === 'failed') {
        if (!chat.current) {
          const created = await analyticsApi.createChat(companyId, eventId, signal);
          signal.throwIfAborted(); chat.current = validateChat(created, companyId, eventId); onChat(created);
        }
        const id = chat.current.id;
        submittedKey.current = draft.current.key;
        pending.current = await analyticsApi.sendMessage(id, draft.current.text, signal, draft.current.key, operation === 'failed');
        signal.throwIfAborted(); mode.current = 'poll';
        const rows = await history(id, signal);
        if (!signal.aborted) setMessages(rows);
      } else if (operation === 'poll' && pending.current) {
        const expected = pending.current.id;
        pending.current = await jobsApi.job(expected, signal);
        if (pending.current.id !== expected) throw normalizeError(502, { message: 'Получено другое задание.' });
      }
      if (!pending.current || !chat.current) return;
      const completed = await waitForJob(pending.current, signal, (next) => {
        if (!signal.aborted) { pending.current = next; setJob(next); }
      });
      const result = completed.result;
      if (!result || result.chat_id !== chat.current.id || typeof result.message_id !== 'string') throw normalizeError(502, { message: 'Задание завершено без ответа выбранного диалога.' });
      const rows = await history(chat.current.id, signal);
      if (!rows.some((item) => item.id === result.message_id && item.role === 'assistant')) throw normalizeError(502, { message: 'Ответ пока отсутствует в серверной истории.' });
      signal.throwIfAborted(); setMessages(rows); pending.current = null;
      if (draft.current.key === submittedKey.current) updateDraft({ text: '', key: crypto.randomUUID() });
    })().catch((reason: unknown) => {
      if (signal.aborted) return;
      if (reason instanceof JobFailure) mode.current = 'failed';
      if (reason instanceof ApiError && [401, 403].includes(reason.status)) setMessages([]);
      setError(reason);
    }).finally(() => { if (!signal.aborted) { active.current = null; setBusy(false); } });
  }, [companyId, eventId, onChat, updateDraft]);

  useEffect(() => {
    if (chat.current) run('restore');
    return () => { active.current?.abort(); };
  }, [run]);

  return {
    text, messages, busy, job, error, sending,
    setText(value: string) { if (!busy) { updateDraft({ text: value, key: crypto.randomUUID() }); mode.current = 'submit'; setError(null); } },
    send() { run('submit'); },
    retry() { run(mode.current); },
    reload() { run('restore'); },
    forbidden: error instanceof ApiError && [401, 403].includes(error.status),
  };
}

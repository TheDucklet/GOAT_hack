import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { HttpClient } from '../../../shared/api/http';
import { demoMe, demoMembership } from '../../../shared/api/mock/fixtures';
import type { ChatState, Message } from '../../../shared/api/types';
import { normalizeError } from '../../../shared/api/errors';

vi.mock('../../../shared/api/index', () => ({ http: new HttpClient('/api', async () => { throw new Error('Unexpected HTTP'); }) }));
import { App } from '../../../app/App';
import { authApi } from '../../auth/api';
import { companiesApi } from '../../companies/api';
import { analyticsApi } from '../api';
import { evidenceApi } from '../../../shared/api/evidence';

const companies = [{ id: 'company-a', name: 'Компания A', profile_version: 'v1' }, { id: 'company-b', name: 'Компания B', profile_version: 'v1' }];
const chat: ChatState = { id: 'chat-b', company_id: 'company-b', event_id: 'event-b', event_title: 'Событие B' };
const answer: Message = { id: 'answer', chat_id: chat.id, sequence: 2, role: 'assistant', text: '<script>unsafe()</script>', created_at: '2026-10-22T12:00:00Z', result: { evidence_refs: ['bank-old'], assumptions: ['Условие из ответа'], unknowns: ['Неизвестна сумма'] } };
beforeEach(() => {
  vi.spyOn(authApi, 'me').mockResolvedValue({ ...demoMe, memberships: companies.map((company) => ({ ...demoMembership, company_id: company.id })) });
  vi.spyOn(companiesApi, 'companies').mockResolvedValue(companies);
  vi.spyOn(analyticsApi, 'feed').mockResolvedValue({ items: [], limit: 20, offset: 0, total: 0 });
  vi.spyOn(analyticsApi, 'chat').mockResolvedValue(chat);
  vi.spyOn(analyticsApi, 'messages').mockResolvedValue([answer]);
  vi.spyOn(analyticsApi, 'sendMessage');
});
const open = () => render(<MemoryRouter initialEntries={['/app/analytics?chat_id=chat-b']}><App /></MemoryRouter>);

it('restores company/event/chat from authorized metadata after reload and clears the workspace on a manual company switch', async () => {
  open();
  const panel = await screen.findByRole('region', { name: 'Диалог по событию' });
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Компания' })).toHaveValue('company-b'));
  expect(await within(panel).findByText(answer.text)).toBeVisible();
  expect(panel).toHaveAttribute('data-event-id', 'event-b'); expect(panel).toHaveAttribute('data-chat-id', 'chat-b');
  expect(analyticsApi.sendMessage).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Компания' }), { target: { value: 'company-a' } });
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Компания' })).toHaveValue('company-a'));
  expect(screen.queryByText(answer.text)).not.toBeInTheDocument();
  expect(screen.getByRole('region', { name: 'Диалог по событию' })).not.toHaveAttribute('data-chat-id');
});

it('shows answer assumptions, unknowns, the policy and dated historical bank evidence without interpreting HTML', async () => {
  vi.spyOn(evidenceApi, 'source').mockResolvedValue({ id: 'bank-old', source_id: 'pdf', kind: 'bank', version: 'v1', excerpt: 'Исторический фрагмент', locator: { page: 3, document_date: '2024-06-01', temporal_status: 'historical', evaluated_on: '2026-10-22' } });
  open();
  await screen.findByText(answer.text);
  expect(screen.getByText('Условие из ответа')).toBeVisible(); expect(screen.getByText('Неизвестна сумма')).toBeVisible();
  expect(document.querySelector('script')).toBeNull();
  const panel = screen.getByRole('region', { name: 'Диалог по событию' });
  expect(within(panel).getByRole('note')).toHaveTextContent('не являются официальной позицией банка');
  fireEvent.click(within(panel).getByText('Основание 1'));
  expect(await screen.findByText(/Исторический материал — не текущая позиция банка/)).toBeVisible();
  expect(screen.getByText(/Дата документа: 2024-06-01/)).toBeVisible();
});

it('prefills contextual follow-up prompts without automatically sending a question', async () => {
  open(); await screen.findByText(answer.text);
  fireEvent.click(screen.getByRole('button', { name: 'Почему это важно нам?' }));
  expect(screen.getByRole('textbox', { name: 'Вопрос по событию' })).toHaveValue('Почему это важно нам?');
  fireEvent.click(screen.getByRole('button', { name: 'Каких данных не хватает?' }));
  expect(screen.getByRole('textbox', { name: 'Вопрос по событию' })).toHaveValue('Каких данных не хватает?');
  expect(analyticsApi.sendMessage).not.toHaveBeenCalled();
});

it('rejects an inaccessible URL chat before reading history', async () => {
  vi.mocked(analyticsApi.chat).mockRejectedValue(normalizeError(403, {})); open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
  expect(analyticsApi.messages).not.toHaveBeenCalled();
  expect(screen.queryByText(answer.text)).not.toBeInTheDocument();
});

it('cancels restoration if the user changes company while metadata is pending', async () => {
  let resolve!: (value: ChatState) => void;
  vi.mocked(analyticsApi.chat).mockReturnValue(new Promise((done) => { resolve = done; })); open();
  const selector = await screen.findByRole('combobox', { name: 'Компания' });
  await waitFor(() => expect(selector).toHaveValue('company-a'));
  fireEvent.change(selector, { target: { value: 'company-b' } });
  await act(async () => resolve(chat));
  expect(screen.queryByText(answer.text)).not.toBeInTheDocument();
  expect(analyticsApi.messages).not.toHaveBeenCalled();
});

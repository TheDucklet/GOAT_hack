import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from './api/client';
import { createMockTransport } from './api/mock/transport';
import { demoCompanies, demoMe, demoMembership } from './api/mock/fixtures';
import { normalizeError } from './api/errors';
import type { Me, Membership } from './api/types';

vi.mock('./api', () => ({ api: new ApiClient('/api', createMockTransport()) }));
import { api } from './api';
import { App } from './App';

let session: Me;
const pending: Membership = { ...demoMembership, id: 'requested', status: 'pending', position_text: '', interests: [] };
beforeEach(() => {
  session = { ...structuredClone(demoMe), memberships: [] };
  vi.spyOn(api, 'me').mockImplementation(async () => structuredClone(session));
  vi.spyOn(api, 'companies').mockImplementation(async () => session.memberships.some((item) => item.status === 'active') ? demoCompanies : []);
});
function open(path = '/app/companies') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>); }
async function requestForm() { return screen.findByRole('form', { name: 'Заявка на компанию' }); }
function fill(form: HTMLElement, companyId = demoMembership.company_id) {
  fireEvent.change(within(form).getByLabelText('Идентификатор компании'), { target: { value: companyId } });
  fireEvent.change(within(form).getByLabelText('Должность'), { target: { value: 'Руководитель нестандартного направления' } });
  fireEvent.change(within(form).getByLabelText('Интересы'), { target: { value: 'Налоги\n\nМеждународные расчёты' } });
}

describe('R-03 memberships and profiles', () => {
  it('keeps analytics closed for a new user and links to the application form', async () => {
    open('/app/analytics');
    expect(await screen.findByRole('heading', { name: 'Нужен доступ к компании' })).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Компания' })).toBeDisabled();
    expect(screen.queryByRole('link', { name: 'Администрирование' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'Подать заявку или проверить статус' }));
    expect(await screen.findByRole('heading', { name: 'Вы ещё не состоите в компании' })).toBeVisible();
    expect(await requestForm()).toBeVisible();
  });

  it('sends only company id and free-form profile fields and shows the returned pending membership', async () => {
    const save = vi.spyOn(api, 'requestMembership').mockResolvedValue(pending);
    open();
    const form = await requestForm();
    fill(form);
    await userEvent.click(within(form).getByRole('button', { name: 'Отправить заявку' }));
    expect(save).toHaveBeenCalledWith({ company_id: demoMembership.company_id, position_text: 'Руководитель нестандартного направления', interests: ['Налоги', 'Международные расчёты'] });
    expect(await screen.findByText('Ожидает подтверждения')).toBeVisible();
    expect(screen.getByText('Заявка отправлена. Ожидайте подтверждения администратора.')).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Компания' })).toBeDisabled();
  });

  it('restores an arbitrary long position and interests from /me after remount without changing user privileges', async () => {
    session.memberships = [structuredClone(demoMembership)];
    const save = vi.spyOn(api, 'updateProfile').mockImplementation(async (id, profile) => {
      const updated = { ...demoMembership, ...profile, id } as Membership;
      session.memberships = [updated];
      return updated;
    });
    const view = open();
    const form = await screen.findByRole('form', { name: 'Профиль: Компания A' });
    const position = 'Руководитель нестандартного направления ' + 'развития бизнеса '.repeat(35);
    fireEvent.change(within(form).getByLabelText('Должность'), { target: { value: position } });
    fireEvent.change(within(form).getByLabelText('Интересы'), { target: { value: 'Новая тема' } });
    await userEvent.click(within(form).getByRole('button', { name: 'Сохранить профиль' }));
    expect(await screen.findByText('Профиль сохранён.')).toBeVisible();
    expect(save).toHaveBeenCalledWith(demoMembership.id, { position_text: position, interests: ['Новая тема'] });
    view.unmount(); open();
    const restored = await screen.findByRole('form', { name: 'Профиль: Компания A' });
    expect(within(restored).getByLabelText('Должность')).toHaveValue(position);
    expect(within(restored).getByLabelText('Интересы')).toHaveValue('Новая тема');
    expect(session.system_role).toBe('user');
    expect(screen.queryByRole('link', { name: 'Администрирование' })).not.toBeInTheDocument();
  });

  it.each([['position_text', 'Должность'], ['interests.0', 'Интересы']])('associates server validation for %s with the correct field', async (field, label) => {
    vi.spyOn(api, 'requestMembership').mockRejectedValue(normalizeError(422, { field_errors: [{ loc: ['body', ...field.split('.')], message: 'Ошибка проверки сервера', type: 'value_error' }] }));
    open();
    const form = await requestForm(); fill(form);
    await userEvent.click(within(form).getByRole('button', { name: 'Отправить заявку' }));
    await waitFor(() => expect(within(form).getByLabelText(label)).toHaveAttribute('aria-invalid', 'true'));
    expect(within(form).getByLabelText(label)).toHaveAccessibleDescription(/Ошибка проверки сервера/);
    expect(within(form).getByLabelText('Должность')).toHaveValue('Руководитель нестандартного направления');
  });

  it.each([[404, 'Компания не найдена'], [409, 'Членство или заявка уже существует']])('shows server %i beside company id and permits correction', async (status, message) => {
    vi.spyOn(api, 'requestMembership').mockRejectedValue(normalizeError(status as number, { message }));
    open();
    const form = await requestForm(); fill(form, 'unknown-company');
    await userEvent.click(within(form).getByRole('button', { name: 'Отправить заявку' }));
    await waitFor(() => expect(within(form).getByLabelText('Идентификатор компании')).toHaveAttribute('aria-invalid', 'true'));
    expect(within(form).getByLabelText('Идентификатор компании')).toHaveAccessibleDescription(new RegExp(String(message)));
    expect(within(form).getByRole('button')).toBeEnabled();
  });

  it('shows forbidden profile updates without claiming success or granting access', async () => {
    session.memberships = [pending];
    vi.spyOn(api, 'updateProfile').mockRejectedValue(normalizeError(403, { message: 'Нет доступа' }));
    open();
    const form = await screen.findByRole('form', { name: `Профиль: ${pending.company_id}` });
    await userEvent.click(within(form).getByRole('button', { name: 'Сохранить профиль' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByText('Профиль сохранён.')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Компания' })).toBeDisabled();
  });

  it('preserves a rejected membership status without making its company available', async () => {
    session.memberships = [{ ...pending, status: 'rejected' }];
    open();
    expect(await screen.findByText('Заявка отклонена')).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Компания' })).toBeDisabled();
  });

  it('refreshes membership approval from the server and then exposes the company', async () => {
    session.memberships = [pending];
    open();
    expect(await screen.findByText('Ожидает подтверждения')).toBeVisible();
    session.memberships = [{ ...pending, status: 'active' }];
    await userEvent.click(screen.getByRole('button', { name: 'Обновить доступ' }));
    expect(await screen.findByRole('option', { name: 'Компания A' })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Доступ открыт')).toBeVisible());
    expect(screen.getByRole('combobox', { name: 'Компания' })).toBeEnabled();
  });

  it('preserves the request after a service outage and prevents duplicate submissions while pending', async () => {
    let resolve!: (membership: Membership) => void;
    const save = vi.spyOn(api, 'requestMembership')
      .mockRejectedValueOnce(normalizeError(503, {}))
      .mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    open();
    const form = await requestForm(); fill(form);
    await userEvent.click(within(form).getByRole('button'));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    expect(within(form).getByLabelText('Идентификатор компании')).toHaveValue(demoMembership.company_id);
    await userEvent.click(within(form).getByRole('button'));
    fireEvent.submit(form);
    expect(save).toHaveBeenCalledTimes(2);
    expect(within(form).getByRole('button')).toBeDisabled();
    resolve(pending);
    expect(await screen.findByText('Ожидает подтверждения')).toBeVisible();
  });
});

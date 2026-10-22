import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeError } from '../../../shared/api/errors';
import type { Membership, User } from '../../../shared/api/types';
import { adminApi } from '../api';
import { UsersPage } from './UsersPage';
import { AdminMembershipsPage } from './MembershipsPage';

const self: User = { id: 'admin-self', email: 'operator@example.org', status: 'active', system_role: 'admin' };
const target: User = { id: 'user-1', email: 'director@example.org', status: 'active', system_role: 'user' };
const member: Membership = { id: 'member-1', user_id: target.id, company_id: 'company-A', status: 'pending', position_text: '<img src=x onerror=alert(1)> Руководитель нового направления', interests: ['Любая тема'] };
const deferred = <T,>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((next) => { resolve = next; }); return { promise, resolve }; };

beforeEach(() => {
  vi.spyOn(adminApi, 'users').mockResolvedValue([self, target]);
  vi.spyOn(adminApi, 'memberships').mockResolvedValue([member]);
  vi.spyOn(adminApi, 'updateUser').mockResolvedValue({ ...target, status: 'blocked' });
  vi.spyOn(adminApi, 'updateMembership').mockResolvedValue({ ...member, status: 'active' });
  // Native dialog provides focus trapping/Escape in browsers. jsdom only needs its open state.
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value(this: HTMLDialogElement) { this.setAttribute('open', ''); } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute('open'); } });
});

describe('R07 user access actions', () => {
  it('requires confirmation, allows cancellation, prevents self-blocking and publishes only the server result', async () => {
    render(<UsersPage currentUserId={self.id} />);
    const own = await screen.findByRole('article', { name: `Пользователь: ${self.email}` });
    expect(within(own).queryByRole('button', { name: 'Заблокировать' })).not.toBeInTheDocument();
    const row = screen.getByRole('article', { name: `Пользователь: ${target.email}` });
    await userEvent.click(within(row).getByRole('button', { name: 'Заблокировать' }));
    expect(adminApi.updateUser).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('Все его текущие сессии будут отозваны');
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }));
    expect(adminApi.updateUser).not.toHaveBeenCalled();
    await userEvent.click(within(row).getByRole('button', { name: 'Заблокировать' }));
    const pending = deferred<User>(); vi.mocked(adminApi.updateUser).mockReturnValueOnce(pending.promise);
    const confirm = screen.getByRole('button', { name: 'Подтвердить изменение' });
    fireEvent.click(confirm); fireEvent.click(confirm);
    expect(adminApi.updateUser).toHaveBeenCalledTimes(1);
    expect(within(row).getByText('Активен', { exact: true })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Сохраняем…' })).toBeDisabled();
    await act(async () => pending.resolve({ ...target, status: 'blocked' }));
    expect(await screen.findByText('Заблокирован', { exact: true })).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('сессии отозваны');
    expect(adminApi.updateUser).toHaveBeenCalledWith(target.id, { status: 'blocked' }, expect.any(AbortSignal));
    await userEvent.click(within(row).getByRole('button', { name: 'Разблокировать' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Прежние сессии не восстанавливаются');
    vi.mocked(adminApi.updateUser).mockResolvedValueOnce(target);
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await within(row).findByText('Активен', { exact: true })).toBeVisible();
  });

  it('keeps the old state on network failure and only retries after a second explicit confirmation', async () => {
    vi.mocked(adminApi.updateUser).mockRejectedValueOnce(normalizeError(0, {}));
    render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    expect(screen.getByText('Изменение не подтверждено.', { exact: false })).toBeVisible();
    expect(screen.queryByText('Заблокирован', { exact: true })).not.toBeInTheDocument();
    expect(adminApi.updateUser).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Повторить изменение' }));
    expect(await screen.findByText('Заблокирован', { exact: true })).toBeVisible();
    expect(adminApi.updateUser).toHaveBeenCalledTimes(2);
  });

  it.each([401, 403])('clears visible records when mutation loses permission (%s)', async (status) => {
    vi.mocked(adminApi.updateUser).mockRejectedValueOnce(normalizeError(status, {}));
    render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.queryByText(target.email, { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('never reports success for a response about another user', async () => {
    vi.mocked(adminApi.updateUser).mockResolvedValueOnce({ ...self, status: 'blocked' });
    render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер не подтвердил');
    expect(screen.queryByText('Заблокирован', { exact: true })).not.toBeInTheDocument();
  });

  it('also hides an earlier success notice when a refreshed list returns forbidden', async () => {
    render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await screen.findByText('Заблокирован', { exact: true })).toBeVisible();
    vi.mocked(adminApi.users).mockRejectedValueOnce(normalizeError(403, {}));
    await userEvent.click(screen.getByRole('button', { name: 'Обновить список' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByText(target.email, { exact: false })).not.toBeInTheDocument();
  });

  it('loads subsequent pages without hiding old rows or confusing a read failure with an empty list', async () => {
    const page = Array.from({ length: 50 }, (_, index) => ({ ...target, id: `user-${index}`, email: `person-${index}@example.org` }));
    vi.mocked(adminApi.users).mockResolvedValueOnce(page).mockRejectedValueOnce(normalizeError(503, {})).mockResolvedValueOnce([self]);
    render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Загрузить ещё' }));
    expect(await screen.findByRole('alert')).toBeVisible();
    expect(screen.getByText(page[0]!.email)).toBeVisible();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText(self.email)).toBeVisible();
    expect(screen.getAllByRole('article')).toHaveLength(51);
    expect(adminApi.users).toHaveBeenLastCalledWith(expect.any(AbortSignal), 50, 50);
  });

  it('aborts reads and writes when leaving the screen and never publishes a late result', async () => {
    const pending = deferred<User>(); vi.mocked(adminApi.updateUser).mockReturnValueOnce(pending.promise);
    const view = render(<UsersPage currentUserId={self.id} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Заблокировать' }));
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    const signal = vi.mocked(adminApi.updateUser).mock.calls[0]![2]!;
    view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve({ ...target, status: 'blocked' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('R07 membership decisions', () => {
  it('shows the exact company, user, arbitrary position and explicit confirmation before approval/rejection', async () => {
    render(<AdminMembershipsPage />);
    const row = await screen.findByRole('article', { name: `Заявка: ${target.email}, company-A` });
    expect(row).toHaveTextContent(member.position_text);
    expect(row.querySelector('img')).toBeNull();
    await userEvent.click(within(row).getByRole('button', { name: 'Подтвердить доступ' }));
    expect(adminApi.updateMembership).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toHaveTextContent('Компания: company-A');
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await within(row).findByText('Доступ открыт')).toBeVisible();
    expect(adminApi.updateMembership).toHaveBeenCalledWith(member.id, { status: 'active' }, expect.any(AbortSignal));
    await userEvent.click(within(row).getByRole('button', { name: 'Отозвать доступ' }));
    vi.mocked(adminApi.updateMembership).mockResolvedValueOnce({ ...member, status: 'rejected' });
    await userEvent.click(screen.getByRole('button', { name: 'Подтвердить изменение' }));
    expect(await within(row).findByText('Заявка отклонена')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('доступ закрыт');
  });

  it('resolves users beyond the first directory page and labels blocked users without changing their status', async () => {
    vi.mocked(adminApi.users).mockResolvedValueOnce(Array.from({ length: 200 }, (_, index) => ({ ...self, id: `other-${index}` }))).mockResolvedValueOnce([{ ...target, status: 'blocked' }]);
    render(<AdminMembershipsPage />);
    expect(await screen.findByRole('article', { name: `Заявка: ${target.email}, company-A` })).toHaveTextContent('Пользователь заблокирован');
    expect(adminApi.users).toHaveBeenLastCalledWith(expect.any(AbortSignal), 200, 200);
    expect(adminApi.updateUser).not.toHaveBeenCalled();
  });

  it('fails closed for a forbidden directory or membership list', async () => {
    vi.mocked(adminApi.users).mockRejectedValueOnce(normalizeError(403, {}));
    render(<AdminMembershipsPage />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подтвердить доступ' })).not.toBeInTheDocument();
  });

  it('shows a real empty state only after successful reads', async () => {
    vi.mocked(adminApi.memberships).mockResolvedValueOnce([]);
    render(<AdminMembershipsPage />);
    expect(await screen.findByText('Записей пока нет.')).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Загружаем список…')).not.toBeInTheDocument());
  });
});

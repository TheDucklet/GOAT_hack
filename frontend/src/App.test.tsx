import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMockTransport } from './api/mock/transport';
import { demoMe, demoPassword } from './api/mock/fixtures';
import { ApiClient } from './api/client';
import { normalizeError } from './api/errors';

vi.mock('./api', () => ({ api: new ApiClient('/api', createMockTransport()) }));
import { api } from './api';
import { App } from './App';

function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}</output>; }
function open(path: string, identity: string | null = null) {
  if (identity) document.cookie = `goat_mock_identity=${identity}; Path=/`;
  return render(<MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter>);
}
async function signIn(email = demoMe.email, password = demoPassword) {
  await userEvent.type(await screen.findByLabelText('Email'), email);
  await userEvent.type(screen.getByLabelText('Пароль'), password);
  await userEvent.click(screen.getByRole('button', { name: 'Войти' }));
}
beforeEach(() => { api.clearSession(); });

describe('R-01 route acceptance', () => {
  it.each(['/app', '/app/analytics', '/app/companies', '/admin'])('redirects an anonymous direct visit to %s to /login', async (path) => {
    open(path);
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/login'));
    expect(await screen.findByRole('heading', { name: 'С возвращением' })).toBeVisible();
  });

  it.each([['/login', 'С возвращением'], ['/register', 'Создать аккаунт']])('opens public URL %s', async (path, title) => {
    open(path);
    await waitFor(() => expect(screen.getByRole('heading', { name: title })).toBeVisible());
    await waitFor(() => expect(screen.getByRole('button', { name: /^(Войти|Зарегистрироваться)$/ })).toBeEnabled());
  });

  it.each([['/app', 'Ваш бизнес в фокусе'], ['/app/analytics', 'Бизнес-аналитика'], ['/admin', 'Администрирование']])('opens authenticated direct URL %s with shared identity', async (path, title) => {
    open(path, 'admin@example.org');
    await waitFor(() => expect(screen.getByRole('heading', { name: title })).toBeVisible());
    expect(await screen.findByRole('option', { name: 'Компания A' })).toBeInTheDocument();
    expect(screen.getByText('admin@example.org')).toBeVisible();
  });

  it('renders the server 403 on /admin for an ordinary user', async () => {
    open('/admin', demoMe.email);
    expect(await screen.findByRole('alert')).toHaveTextContent('Нет доступа');
    expect(screen.queryByText('Оценок полезности')).not.toBeInTheDocument();
  });

  it('returns to the requested route after login', async () => {
    open('/app/analytics');
    await signIn();
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Бизнес-аналитика' })).toBeVisible());
    expect(screen.getByTestId('location')).toHaveTextContent('/app/analytics');
  });

  it('puts server 422 errors beside each field with accessible associations', async () => {
    open('/register');
    const form = await screen.findByRole('form', { name: 'Регистрация' });
    await waitFor(() => expect(within(form).getByRole('button')).toBeEnabled());
    fireEvent.submit(form);
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Введите корректный email.');
    expect(screen.getByLabelText('Пароль')).toHaveAccessibleDescription('Пароль должен содержать от 10 до 256 символов.');
  });

  it('shows 503 and keeps the form available to retry', async () => {
    open('/login');
    await signIn('unavailable@example.org');
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    expect(screen.getByRole('button', { name: 'Войти' })).toBeEnabled();
    expect(screen.getByLabelText('Email')).toHaveValue('unavailable@example.org');
  });

  it('shows bad credentials without a redirect loop, then allows retry', async () => {
    open('/login');
    await signIn(demoMe.email, 'wrong-password');
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
  });

  it('associates an occupied email error with the registration email field', async () => {
    open('/register');
    await userEvent.type(await screen.findByLabelText('Email'), demoMe.email);
    await userEvent.type(screen.getByLabelText('Пароль'), demoPassword);
    await userEvent.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true'));
    expect(screen.getByLabelText('Email')).toHaveAccessibleDescription('Email уже зарегистрирован.');
    expect(screen.getByTestId('location')).toHaveTextContent('/register');
  });

  it('logout uses the same client and returns to login', async () => {
    open('/app', demoMe.email);
    await userEvent.click(await screen.findByRole('button', { name: 'Выйти' }));
    expect(await screen.findByRole('heading', { name: 'С возвращением' })).toBeVisible();
    expect(document.cookie).not.toContain('goat_mock_identity=');
  });

  it('shows a temporary /me outage without treating it as a missing session', async () => {
    vi.spyOn(api, 'me').mockRejectedValueOnce(normalizeError(503, {}));
    open('/app');
    expect(await screen.findByRole('alert')).toHaveTextContent('Сервис временно недоступен');
    expect(screen.getByTestId('location')).toHaveTextContent('/app');
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('heading', { name: 'С возвращением' })).toBeVisible();
  });

  it('redirects to login when a session expires during a protected request', async () => {
    open('/app', 'admin@example.org');
    await screen.findByRole('option', { name: 'Компания A' });
    document.cookie = 'goat_mock_identity=; Path=/; Max-Age=0';
    await userEvent.click(screen.getByRole('link', { name: 'Администрирование' }));
    expect(await screen.findByRole('heading', { name: 'С возвращением' })).toBeVisible();
    expect(screen.getByTestId('location')).toHaveTextContent('/login');
  });
});

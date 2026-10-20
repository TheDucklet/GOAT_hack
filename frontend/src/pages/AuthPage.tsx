import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api';
import { ApiError } from '../api/errors';
import { useAuth } from '../auth/AuthProvider';
import { ErrorNotice } from '../components/ErrorNotice';
import { config } from '../config';

const demo = import.meta.env.DEV && config.apiMode === 'mock'
  ? await import('../api/mock/fixtures')
  : null;

export function AuthPage({ register = false }: { register?: boolean }) {
  const { state, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fields, setFields] = useState<Record<string, string[]>>({});
  const returnTo: unknown = (location.state as { from?: unknown } | null)?.from;
  const destination = typeof returnTo === 'string' && /^\/(app(?:[/?]|$)|admin(?:[/?]|$))/.test(returnTo) ? returnTo : '/app';
  if (state.status === 'authenticated') return <Navigate to={destination} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true); setError(null); setFields({});
    try {
      if (register) {
        await api.register({ email, password });
        setPassword('');
        navigate('/login', { replace: true, state: { registered: true } });
      } else {
        await login({ email, password });
        setPassword('');
        navigate(destination, { replace: true });
      }
    } catch (reason) {
      setError(reason);
      if (reason instanceof ApiError) setFields(register && reason.status === 409 && ['email_exists', 'email_taken'].includes(reason.body.code)
        ? { email: [reason.message] } : reason.fieldErrors);
    } finally { setPending(false); }
  }
  return <main className="auth-shell">
    <section className="auth-intro"><Link className="brand" to="/login"><span className="brand-mark">А</span>Альфа-Бизнес</Link><div><span className="eyebrow">Для решений, которые имеют значение</span><h1>События рынка.<br />В контексте<br />вашего бизнеса.</h1><p>Новости, аналитика банка и взгляд на возможное влияние событий на вашу компанию.</p></div><span className="intro-footer">Бизнес-аналитика · GOAT_hack</span></section>
    <section className="auth-form-panel"><div className="auth-form-wrap"><span className="eyebrow">Личный кабинет</span><h2>{register ? 'Создать аккаунт' : 'С возвращением'}</h2><p className="muted">{register ? 'После регистрации войдите и запросите доступ к компании.' : 'Войдите, чтобы открыть рабочее пространство.'}</p>
      {(location.state as { registered?: boolean } | null)?.registered && <p className="success-notice" role="status">Аккаунт создан. Войдите с вашим email и паролем.</p>}
      {error != null && <ErrorNotice error={error} showFields={false} />}
      {state.status === 'error' && <ErrorNotice error={state.error} />}
      <form onSubmit={submit} noValidate aria-label={register ? 'Регистрация' : 'Вход'}>
        <div className="field"><label htmlFor="email">Email</label><input id="email" name="email" type="email" autoComplete="username" value={email} onChange={(event) => { setEmail(event.target.value); setFields((current) => ({ ...current, email: [] })); }} aria-invalid={!!fields.email?.length} aria-describedby={fields.email?.length ? 'email-error' : undefined} required />
          {!!fields.email?.length && <p id="email-error" className="field-error">{fields.email.join(' ')}</p>}</div>
        <div className="field"><label htmlFor="password">Пароль</label><input id="password" name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={(event) => { setPassword(event.target.value); setFields((current) => ({ ...current, password: [] })); }} aria-invalid={!!fields.password?.length} aria-describedby={fields.password?.length ? 'password-error' : undefined} required />
          {register && <p className="field-hint">От 10 до 256 символов.</p>}
          {!!fields.password?.length && <p id="password-error" className="field-error">{fields.password.join(' ')}</p>}</div>
        <button className="button primary full" disabled={pending || state.status === 'loading'}>{pending ? 'Подождите…' : register ? 'Зарегистрироваться' : 'Войти'}</button>
      </form>
      <p className="auth-switch">{register ? 'Уже есть аккаунт? ' : 'Нет аккаунта? '}<Link to={register ? '/login' : '/register'}>{register ? 'Войти' : 'Зарегистрироваться'}</Link></p>
      {demo && <div className="demo-notice"><strong>Демонстрационный вход</strong><p>{demo.demoMe.email} или admin@example.org</p><p>Пароль: {demo.demoPassword}</p><small>Синтетические аккаунты. Данные не отправляются на сервер.</small></div>}
    </div></section>
  </main>;
}

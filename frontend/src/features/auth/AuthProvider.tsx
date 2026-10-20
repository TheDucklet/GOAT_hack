import { http } from '../../shared/api';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { authApi } from './api';
import { ApiError } from '../../shared/api/errors';
import type { Credentials, Me, Membership } from '../../shared/api/types';

type AuthState = { status: 'loading' } | { status: 'anonymous' } | { status: 'error'; error: unknown } | { status: 'authenticated'; session: Me };
interface AuthContextValue {
  state: AuthState;
  refresh(): Promise<void>;
  login(credentials: Credentials): Promise<void>;
  logout(): Promise<void>;
  reloadSession(): Promise<void>;
  recordMembership(membership: Membership): void;
}
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' });
  const refresh = useCallback(async () => {
    setState({ status: 'loading' });
    try { setState({ status: 'authenticated', session: await authApi.me() }); }
    catch (error) { setState(error instanceof ApiError && error.status === 401 ? { status: 'anonymous' } : { status: 'error', error }); }
  }, []);
  useEffect(() => {
    const unsubscribe = http.onUnauthorized(() => setState({ status: 'anonymous' }));
    void refresh();
    return unsubscribe;
  }, [refresh]);
  const login = async (credentials: Credentials) => { setState({ status: 'authenticated', session: await authApi.login(credentials) }); };
  const logout = async () => { await authApi.logout(); setState({ status: 'anonymous' }); };
  const reloadSession = async () => {
    const session = await authApi.me();
    setState((current) => current.status === 'authenticated' && current.session.id === session.id ? { status: 'authenticated', session } : current);
  };
  const recordMembership = (membership: Membership) => setState((current) => {
    if (current.status !== 'authenticated' || current.session.id !== membership.user_id) return current;
    return { ...current, session: { ...current.session, memberships: [
      ...current.session.memberships.filter((item) => item.id !== membership.id), membership,
    ] } };
  });
  return <AuthContext.Provider value={{ state, refresh, login, logout, reloadSession, recordMembership }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('AuthProvider is required');
  return context;
}

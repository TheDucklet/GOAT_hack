import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api } from '../api';
import { ApiError } from '../api/errors';
import type { Credentials, Me, Membership } from '../api/types';

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
    try { setState({ status: 'authenticated', session: await api.me() }); }
    catch (error) { setState(error instanceof ApiError && error.status === 401 ? { status: 'anonymous' } : { status: 'error', error }); }
  }, []);
  useEffect(() => {
    const unsubscribe = api.onUnauthorized(() => setState({ status: 'anonymous' }));
    void refresh();
    return unsubscribe;
  }, [refresh]);
  const login = async (credentials: Credentials) => { setState({ status: 'authenticated', session: await api.login(credentials) }); };
  const logout = async () => { await api.logout(); setState({ status: 'anonymous' }); };
  const reloadSession = async () => {
    const session = await api.me();
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

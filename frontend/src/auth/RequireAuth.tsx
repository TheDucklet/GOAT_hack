import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './AuthProvider';
import { ErrorNotice } from '../components/ErrorNotice';

export function RequireAuth() {
  const { state, refresh } = useAuth();
  const location = useLocation();
  if (state.status === 'loading') return <p role="status" className="page-state">Проверяем сессию…</p>;
  if (state.status === 'error') return <main className="page-state"><ErrorNotice error={state.error} retry={() => void refresh()} /></main>;
  if (state.status === 'anonymous') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

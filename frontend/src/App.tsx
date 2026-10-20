import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthProvider';
import { RequireAuth } from './auth/RequireAuth';
import { AppLayout } from './layout/AppLayout';
import { AdminPage } from './pages/AdminPage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { AuthPage } from './pages/AuthPage';
import { OverviewPage } from './pages/OverviewPage';
import { MembershipsPage } from './pages/MembershipsPage';

export function App() {
  return <AuthProvider><Routes>
    <Route path="/" element={<Navigate to="/app" replace />} />
    <Route path="/login" element={<AuthPage key="login" />} />
    <Route path="/register" element={<AuthPage key="register" register />} />
    <Route element={<RequireAuth />}><Route element={<AppLayout />}>
      <Route path="/app" element={<OverviewPage />} />
      <Route path="/app/companies" element={<MembershipsPage />} />
      <Route path="/app/analytics" element={<AnalyticsPage />} />
      <Route path="/admin" element={<AdminPage />} />
    </Route></Route>
    <Route path="*" element={<main className="page-state"><h1>Страница не найдена</h1><Link to="/app">На главную</Link></main>} />
  </Routes></AuthProvider>;
}

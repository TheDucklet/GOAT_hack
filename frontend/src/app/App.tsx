import { CompanyProvider } from '../features/companies/CompanyProvider';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from '../features/auth/AuthProvider';
import { RequireAuth } from '../features/auth/RequireAuth';
import { AppLayout } from './layout/AppLayout';
import { AdminPage } from '../features/admin/AdminPage';
import { AnalyticsPage } from '../features/analytics/AnalyticsPage';
import { AuthPage } from '../features/auth/AuthPage';
import { OverviewPage } from '../features/overview/OverviewPage';
import { MembershipsPage } from '../features/companies/MembershipsPage';

export function App() {
  return <AuthProvider><Routes>
    <Route path="/" element={<Navigate to="/app" replace />} />
    <Route path="/login" element={<AuthPage key="login" />} />
    <Route path="/register" element={<AuthPage key="register" register />} />
    <Route element={<RequireAuth />}><Route element={<CompanyProvider><AppLayout /></CompanyProvider>}>
      <Route path="/app" element={<OverviewPage />} />
      <Route path="/app/companies" element={<MembershipsPage />} />
      <Route path="/app/analytics" element={<AnalyticsPage />} />
      <Route path="/admin" element={<AdminPage />} />
    </Route></Route>
    <Route path="*" element={<main className="page-state"><h1>Страница не найдена</h1><Link to="/app">На главную</Link></main>} />
  </Routes></AuthProvider>;
}

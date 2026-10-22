import { CompanyProvider } from '../features/companies/CompanyProvider';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider, useAuth } from '../features/auth/AuthProvider';
import { RequireAuth } from '../features/auth/RequireAuth';
import { AppLayout } from './layout/AppLayout';
import { AdminPage } from '../features/admin/AdminPage';
import { AdminLayout } from '../features/admin/AdminLayout';
import { UsersPage } from '../features/admin/access/UsersPage';
import { AdminMembershipsPage } from '../features/admin/access/MembershipsPage';
import { DocumentsPage } from '../features/admin/materials/DocumentsPage';
import { NewsPage } from '../features/admin/materials/NewsPage';
import { JobsPage } from '../features/admin/materials/JobsPage';
import { AnalyticsPage } from '../features/analytics/AnalyticsPage';
import { AuthPage } from '../features/auth/AuthPage';
import { OverviewPage } from '../features/overview/OverviewPage';
import { MembershipsPage } from '../features/companies/MembershipsPage';

function AnalyticsRoute() {
  const { state } = useAuth();
  return state.status === 'authenticated' ? <AnalyticsPage userId={state.session.id} /> : null;
}

function AdminUsersRoute() {
  const { state } = useAuth();
  return state.status === 'authenticated' ? <UsersPage currentUserId={state.session.id} /> : null;
}

export function App() {
  return <AuthProvider><Routes>
    <Route path="/" element={<Navigate to="/app" replace />} />
    <Route path="/login" element={<AuthPage key="login" />} />
    <Route path="/register" element={<AuthPage key="register" register />} />
    <Route element={<RequireAuth />}><Route element={<CompanyProvider><AppLayout /></CompanyProvider>}>
      <Route path="/app" element={<OverviewPage />} />
      <Route path="/app/companies" element={<MembershipsPage />} />
      <Route path="/app/analytics" element={<AnalyticsRoute />} />
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<AdminPage />} />
        <Route path="users" element={<AdminUsersRoute />} />
        <Route path="memberships" element={<AdminMembershipsPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="news" element={<NewsPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="users/memberships" element={<Navigate to="/admin/memberships" replace />} />
      </Route>
    </Route></Route>
    <Route path="*" element={<main className="page-state"><h1>Страница не найдена</h1><Link to="/app">На главную</Link></main>} />
  </Routes></AuthProvider>;
}

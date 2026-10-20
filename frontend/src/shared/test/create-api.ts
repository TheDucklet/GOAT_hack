// Test composition only: production features depend directly on their own API modules.
import { HttpClient, type Transport } from '../api/http';
import { createAuthApi } from '../../features/auth/api';
import { createCompaniesApi } from '../../features/companies/api';
import { createAnalyticsApi } from '../../features/analytics/api';
import { createAdminApi } from '../../features/admin/api';
import { createJobsApi } from '../api/jobs';
export function createTestApi(baseUrl: string, transport?: Transport) {
  const client = new HttpClient(baseUrl, transport);
  return { ...createAuthApi(client), ...createCompaniesApi(client), ...createAnalyticsApi(client), ...createAdminApi(client), ...createJobsApi(client),
    request: client.request.bind(client), clearSession: client.clearSession.bind(client), onUnauthorized: client.onUnauthorized.bind(client) };
}

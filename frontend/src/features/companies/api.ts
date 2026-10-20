import { http } from '../../shared/api';
import type { HttpClient } from '../../shared/api/http';
import type { Company, Membership, MembershipProfile, MembershipRequest } from '../../shared/api/types';
export function createCompaniesApi(client: HttpClient) {
  return {
    companies(signal?: AbortSignal) { return client.request<Company[]>('/companies', { signal }); },
    requestMembership(body: MembershipRequest) { return client.request<Membership>('/memberships/requests', { method: 'POST', body }); },
    updateProfile(id: string, body: MembershipProfile) { return client.request<Membership>(`/memberships/${encodeURIComponent(id)}/profile`, { method: 'PATCH', body }); },
  };
}
export const companiesApi = createCompaniesApi(http);

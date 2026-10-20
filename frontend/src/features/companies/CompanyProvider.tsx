import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { Company } from '../../shared/api/types';
import { useAuth } from '../auth/AuthProvider';
import { companiesApi } from './api';

interface CompanySelection {
  company: Company | null;
  companies: Company[];
  loading: boolean;
  error: unknown;
  selectCompany(id: string): void;
  retry(): void;
}
const CompanyContext = createContext<CompanySelection | null>(null);

export function useCompanySelection() {
  const context = useContext(CompanyContext);
  if (!context) throw new Error('CompanyProvider is required');
  return context;
}
export const useCompany = () => useCompanySelection().company;
export const useCompanies = () => useCompanySelection().companies;

export function CompanyProvider({ children }: { children: ReactNode }) {
  const { state } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const activeIds = state.status === 'authenticated' ? state.session.memberships.filter((item) => item.status === 'active').map((item) => item.company_id) : [];
  const accessKey = JSON.stringify(activeIds.sort());

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    void companiesApi.companies(controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      setCompanies(result);
      setCompanyId((current) => result.some((company) => company.id === current) ? current : result[0]?.id || '');
    }).catch((reason: unknown) => { if (!controller.signal.aborted) { setCompanies([]); setError(reason); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accessKey, attempt]);

  const available = companies.filter((item) => activeIds.includes(item.id));
  const company = available.find((item) => item.id === companyId) || null;
  return <CompanyContext.Provider value={{ company, companies: available, loading, error, selectCompany: setCompanyId, retry: () => setAttempt((value) => value + 1) }}>{children}</CompanyContext.Provider>;
}

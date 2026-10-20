import examples from '../../../../docs/contracts/examples.json';
import type { components } from '../schema';
import type { Company, Insight } from '../types';

export function contractExample<K extends keyof components['schemas']>(name: string, schema: K): components['schemas'][K] {
  const example = examples.find((entry) => entry.name === name && entry.schema === schema);
  if (!example) throw new Error(`Missing A-01 example: ${name}/${schema}`);
  // Each example is schema-validated in contracts.test.ts, including this lookup.
  return structuredClone(example.data) as components['schemas'][K];
}

export const demoPassword = 'Demo-password-2026';
export const demoMe = contractExample('me', 'MeOut');
export const demoUser = contractExample('successful_user', 'UserOut');
export const demoMembership = contractExample('membership', 'MembershipOut');
export const demoFeed = contractExample('feed', 'FeedOut');
export const demoChat = contractExample('chat', 'ChatOut');
export const demoJob = contractExample('pending_job', 'JobOut');
export const demoStats = contractExample('stats', 'StatsOut');
export const demoError = contractExample('error', 'ErrorOut');

// CompanyOut and the InsightOut envelope have no standalone A-01 example.
// These envelopes are composed; nested AI content is the original example.
export const demoCompanies: Company[] = [{ id: demoMembership.company_id, name: 'Компания A', profile_version: 'demo-v1' }];
export const demoInsight: Insight = {
  id: 'example-insight', company_id: demoChat.company_id, event_id: demoChat.event_id,
  versions: { profile: 'demo-v1' }, result: contractExample('insufficient_data', 'InsightResult'),
};

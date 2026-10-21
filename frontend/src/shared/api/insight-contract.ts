import notice from '../../../../docs/contracts/notice-policy.json';
import type { Insight, InsightResultV2 } from './types';

// Application policy is authoritative even for tagless v1 and incomplete results.
export const insightNotice = Object.freeze(notice);

export function isInsightV2(result: Insight['result']): result is InsightResultV2 {
  if (!('schema_version' in result)) return false;
  if (result.schema_version !== 'v2') throw new Error('Unsupported insight schema version');
  return true;
}

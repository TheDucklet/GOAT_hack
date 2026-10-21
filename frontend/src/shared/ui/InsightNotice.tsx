import { insightNotice } from '../api/insight-contract';

// No model-supplied text or hide toggle: the notice belongs to the application.
export function InsightNotice() {
  return <p role="note" data-policy-version={insightNotice.policy_version}>{insightNotice.disclaimer}</p>;
}

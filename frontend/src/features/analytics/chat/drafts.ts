// Draft text stays in this tab's memory, scoped to the signed-in user and context.
// No question, cookie or token is written to browser storage or the URL.
export interface ChatDraft { text: string; key: string }
const drafts = new Map<string, ChatDraft>();
export const draftScope = (userId: string, companyId: string, eventId: string) => JSON.stringify([userId, companyId, eventId]);
export function readDraft(scope: string): ChatDraft { return drafts.get(scope) || { text: '', key: crypto.randomUUID() }; }
export function saveDraft(scope: string, draft: ChatDraft) {
  drafts.delete(scope);
  if (draft.text) drafts.set(scope, draft);
  while (drafts.size > 30) drafts.delete(drafts.keys().next().value!);
}

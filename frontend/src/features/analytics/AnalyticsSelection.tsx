import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { Chat, FeedItem, Insight } from '../../shared/api/types';

interface Selection {
  userId: string;
  companyId: string;
  event: FeedItem | null;
  chat: Chat | null;
  insightId: string | null;
  selectEvent(event: FeedItem | null, insightId?: string | null): void;
  setChat(chat: Chat | null): void;
  rememberInsight(insight: Insight): void;
}
const Context = createContext<Selection | null>(null);

export function useAnalyticsSelection() {
  const selection = useContext(Context);
  if (!selection) throw new Error('AnalyticsSelectionProvider is required');
  return selection;
}

interface SelectionProps { companyId: string; userId?: string; children: ReactNode; initialEvent?: FeedItem; initialChat?: Chat }
function CompanySelection({ companyId, userId = '', children, initialEvent, initialChat }: SelectionProps) {
  const [selection, setSelection] = useState<{ event: FeedItem | null; chat: Chat | null; insightId: string | null }>({ event: initialEvent || null, chat: initialChat || null, insightId: null });
  const selectEvent = useCallback((next: FeedItem | null, insightId: string | null = null) => {
    setSelection((current) => current.event === next && (!insightId || current.insightId === insightId) ? current : {
      event: next, insightId, chat: next?.event_id === current.event?.event_id ? current.chat : null,
    });
  }, []);
  const setChat = useCallback((next: Chat | null) => {
    setSelection((current) => {
      if (next && (next.company_id !== companyId || next.event_id !== current.event?.event_id)) return current;
      return { ...current, chat: next };
    });
  }, [companyId]);
  const rememberInsight = useCallback((insight: Insight) => {
    setSelection((current) => insight.company_id === companyId && insight.event_id === current.event?.event_id
      ? { ...current, insightId: insight.id } : current);
  }, [companyId]);
  return <Context.Provider value={{ companyId, userId, ...selection, selectEvent, setChat, rememberInsight }}>{children}</Context.Provider>;
}

// A company change resets the entire workspace, including in-flight requests.
export function AnalyticsSelectionProvider(props: SelectionProps) {
  return <CompanySelection key={props.companyId} {...props} />;
}

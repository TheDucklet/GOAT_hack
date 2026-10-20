import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { Chat, FeedItem } from '../../shared/api/types';

interface Selection {
  companyId: string;
  event: FeedItem | null;
  chat: Chat | null;
  selectEvent(event: FeedItem | null): void;
  setChat(chat: Chat | null): void;
}
const Context = createContext<Selection | null>(null);

export function useAnalyticsSelection() {
  const selection = useContext(Context);
  if (!selection) throw new Error('AnalyticsSelectionProvider is required');
  return selection;
}

function CompanySelection({ companyId, children }: { companyId: string; children: ReactNode }) {
  const [selection, setSelection] = useState<{ event: FeedItem | null; chat: Chat | null }>({ event: null, chat: null });
  const selectEvent = useCallback((next: FeedItem | null) => {
    setSelection((current) => current.event === next ? current : {
      event: next, chat: next?.event_id === current.event?.event_id ? current.chat : null,
    });
  }, []);
  const setChat = useCallback((next: Chat | null) => {
    setSelection((current) => {
      if (next && (next.company_id !== companyId || next.event_id !== current.event?.event_id)) return current;
      return { ...current, chat: next };
    });
  }, [companyId]);
  return <Context.Provider value={{ companyId, ...selection, selectEvent, setChat }}>{children}</Context.Provider>;
}

// A company change resets the entire workspace, including in-flight requests.
export function AnalyticsSelectionProvider(props: { companyId: string; children: ReactNode }) {
  return <CompanySelection key={props.companyId} {...props} />;
}

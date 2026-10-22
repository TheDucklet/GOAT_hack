import { useEffect, useRef } from 'react';
import { interactionApi } from './api';

// Only a validated, saved card can be opened or impressed. News alone is not a card.
export function useInsightTelemetry(company: string, event: string, insight: string) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    const send = (event_type: 'open' | 'impression') => {
      void interactionApi.track(company, { event_id: event, insight_id: insight, event_type }, controller.signal).catch(() => {});
    };
    send('open');
    let timer: ReturnType<typeof setTimeout> | undefined;
    let visible = false;
    let sent = false;
    const clear = () => { clearTimeout(timer); timer = undefined; };
    const schedule = () => {
      clear();
      if (visible && document.visibilityState === 'visible' && !sent) timer = setTimeout(() => { sent = true; send('impression'); }, 1000);
    };
    const observer = typeof IntersectionObserver === 'undefined' ? null : new IntersectionObserver(([entry]) => {
      visible = !!entry && entry.isIntersecting && entry.intersectionRatio >= 0.5; schedule();
    }, { threshold: [0, 0.5, 1] });
    if (ref.current) observer?.observe(ref.current);
    document.addEventListener('visibilitychange', schedule);
    return () => { controller.abort(); clear(); observer?.disconnect(); document.removeEventListener('visibilitychange', schedule); };
  }, [company, event, insight]);
  return ref;
}

import { useEffect, useRef, useState } from "react";
import { STREAMING_ID } from "../data/chatState";
import type { ChatMessage } from "../data/types";

export interface UnreadState {
  seen: number | null;
  unread: number;
}

export const answeredCount = (messages: ChatMessage[]) =>
  messages.filter((m) => (m.role === "assistant" || m.role === "human") && m.id !== STREAMING_ID).length;

export function nextUnread(prev: UnreadState, answered: number, open: boolean): UnreadState {
  if (open || prev.seen === null) return { seen: answered, unread: 0 };
  return answered > prev.seen ? { seen: prev.seen, unread: answered - prev.seen } : prev;
}

export function useUnread(answered: number, open: boolean, onNew: () => void, ready = true): number {
  const state = useRef<UnreadState>({ seen: null, unread: 0 });
  const [unread, setUnread] = useState(0);
  const notify = useRef(onNew);
  notify.current = onNew;

  useEffect(() => {
    if (!ready) return;
    const next = nextUnread(state.current, answered, open);
    if (next.unread > state.current.unread) notify.current();
    state.current = next;
    setUnread(next.unread);
  }, [answered, open, ready]);

  return unread;
}

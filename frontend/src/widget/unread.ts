import { useEffect, useRef, useState } from "react";
import { STREAMING_ID } from "../data/chatState";
import type { ChatMessage } from "../data/types";

export interface UnreadState {
  /** Answers already seen, or null until the first look at the conversation. */
  seen: number | null;
  unread: number;
}

/** Finished answers (the assistant's or a person's) only: the one still streaming is not "new" yet. */
export const answeredCount = (messages: ChatMessage[]) =>
  messages.filter((m) => (m.role === "assistant" || m.role === "human") && m.id !== STREAMING_ID).length;

/**
 * Answers that arrived while the panel was closed. The first look only sets the baseline, so
 * opening a page with an old conversation does not light up a badge; opening the panel clears it.
 */
export function nextUnread(prev: UnreadState, answered: number, open: boolean): UnreadState {
  if (open || prev.seen === null) return { seen: answered, unread: 0 };
  return answered > prev.seen ? { seen: prev.seen, unread: answered - prev.seen } : prev;
}

/**
 * The unread count for the launcher badge; `onNew` runs when it grows (to play the sound).
 * `ready` is false until the conversation has been read from the server (or there is something
 * to read): a stored conversation that arrives after the first look is the baseline, not news.
 */
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

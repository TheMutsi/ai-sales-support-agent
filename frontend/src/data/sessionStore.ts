import type { Session } from "./types";

/** A conversation stays resumable for 24 hours after its last activity. */
export const CONVERSATION_WINDOW_MS = 24 * 60 * 60 * 1000;

interface Stored {
  session: Session;
  lastActivity: number;
}

/**
 * The session in `localStorage` (the iframe is same-origin with the shop's page), so every tab of
 * the shop shares one conversation. A `BroadcastChannel` tells the other tabs when it changes.
 * Storage can throw (private windows, blocked site data): then the widget still works, it just
 * starts a new conversation on every page load.
 */
export function createSessionStore(
  apiKey: string,
  storage: Storage = localStorage,
  now: () => number = Date.now,
  channel: BroadcastChannel | null = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(`mew:${apiKey}`),
) {
  const key = `mew:session:${apiKey}`;
  const listeners = new Set<() => void>();
  channel?.addEventListener("message", () => listeners.forEach((l) => l()));

  const read = (): Stored | null => {
    try {
      return JSON.parse(storage.getItem(key) ?? "null");
    } catch {
      return null;
    }
  };
  const write = (stored: Stored | null) => {
    try {
      if (stored) storage.setItem(key, JSON.stringify(stored));
      else storage.removeItem(key);
    } catch {
      /* storage unavailable: keep working without persistence */
    }
    channel?.postMessage("changed");
  };

  return {
    /** The saved session, or null if there is none, the window passed, or the server's expiry did. */
    load(): Session | null {
      const stored = read();
      if (!stored) return null;
      const expired = Date.parse(stored.session.expiresAt) <= now();
      return expired || now() - stored.lastActivity > CONVERSATION_WINDOW_MS ? null : stored.session;
    },
    save: (session: Session) => write({ session, lastActivity: now() }),
    /** Call when the visitor sends a message: it restarts the 24 hour window. */
    touch() {
      const stored = read();
      if (stored) write({ ...stored, lastActivity: now() });
    },
    clear: () => write(null),
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

export type SessionStore = ReturnType<typeof createSessionStore>;

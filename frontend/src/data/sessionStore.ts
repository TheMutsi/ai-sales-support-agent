import type { Session } from "./types";

export const CONVERSATION_WINDOW_MS = 24 * 60 * 60 * 1000;

interface Stored {
  session: Session;
  lastActivity: number;
}

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
    } catch {}
    channel?.postMessage("changed");
  };

  return {
    load(): Session | null {
      const stored = read();
      if (!stored) return null;
      const expired = Date.parse(stored.session.expiresAt) <= now();
      return expired || now() - stored.lastActivity > CONVERSATION_WINDOW_MS ? null : stored.session;
    },
    save: (session: Session) => write({ session, lastActivity: now() }),
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

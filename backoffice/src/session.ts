import type { AdminSession } from "./api";

// Per tab and gone when it closes: the placeholder login is not worth remembering longer.
const KEY = "mewflow-backoffice-session";

export function loadSession(): AdminSession | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    const session: AdminSession | null = raw ? JSON.parse(raw) : null;
    return session && new Date(session.expires_at) > new Date() ? session : null;
  } catch {
    return null;
  }
}

export function saveSession(session: AdminSession | null): void {
  try {
    if (session) sessionStorage.setItem(KEY, JSON.stringify(session));
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage can be blocked; the session then lives until the page reloads.
  }
}

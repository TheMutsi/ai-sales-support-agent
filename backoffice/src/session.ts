import type { AdminSession } from "./api";

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
  } catch {}
}

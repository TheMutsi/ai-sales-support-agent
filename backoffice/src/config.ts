export const LEVELS = ["anonymous", "store_login", "otp_login", "order_lookup"] as const;
export const SCOPES = [
  "kb:read",
  "customer:read",
  "order:read",
  "ticket:create",
  "subscription:change",
  "refund:request",
] as const;

export type Overrides = Record<string, string[]>;

export function parseOrigins(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

export function buildOverrides(custom: Overrides): Overrides | null {
  const entries = Object.entries(custom).filter(([level]) => (LEVELS as readonly string[]).includes(level));
  return entries.length ? Object.fromEntries(entries) : null;
}

export function toggleScope(scopes: string[], scope: string): string[] {
  return scopes.includes(scope) ? scopes.filter((s) => s !== scope) : [...scopes, scope];
}

const MESSAGES: Record<string, string> = {
  forbidden: "Your role may not do this.",
  wrong_tenant: "This session belongs to another tenant.",
  session_expired: "Your session expired. Enter again.",
  invalid_session: "Your session is not valid. Enter again.",
  not_waiting: "Someone else already took this conversation.",
  not_active: "Nobody is in this conversation yet. Join it first.",
  not_in_handoff: "This conversation was already closed.",
};

export function messageFor(status: number, code: string): string {
  return MESSAGES[code] ?? (status === 422 ? code : "The change was refused.");
}

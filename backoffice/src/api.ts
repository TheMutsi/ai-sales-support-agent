// The admin API (`/api/admin`), typed. Errors carry the backend's `detail.code`, so a page can
// react to "session_expired" or "forbidden" without parsing messages.

export type Role = "viewer" | "agent" | "admin" | "operator";

export interface AdminSession {
  token: string;
  role: Role;
  name: string;
  tenant_id: string | null;
  expires_at: string;
  permissions: string[];
}

export interface TenantOption {
  id: string;
  name: string;
}

export interface TenantConfig extends TenantOption {
  allowed_origins: string[];
  scope_overrides: Record<string, string[]> | null;
}

export interface ConfigUpdate {
  allowed_origins?: string[];
  scope_overrides?: Record<string, string[]> | null;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(code);
  }
}

async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/admin${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    // FastAPI sends `{detail: {code}}` for ours and `{detail: [...]}` for a validation error.
    const detail = body?.detail;
    const code = Array.isArray(detail)
      ? detail.map((problem: { msg?: string }) => problem.msg).join("; ")
      : typeof detail?.code === "string"
        ? detail.code
        : "request_failed";
    throw new ApiError(response.status, code);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export const listLoginOptions = () => request<TenantOption[]>("/login-options");

export const login = (role: Role, tenantId: string | null, name?: string) =>
  request<AdminSession>("/session", {
    method: "POST",
    body: JSON.stringify({ role, tenant_id: tenantId, name: name || null }),
  });

export const listTenants = (token: string) => request<TenantOption[]>("/tenants", {}, token);

export const readConfig = (token: string, tenantId: string) =>
  request<TenantConfig>(`/tenants/${tenantId}/config`, {}, token);

export const updateConfig = (token: string, tenantId: string, update: ConfigUpdate) =>
  request<TenantConfig>(
    `/tenants/${tenantId}/config`,
    { method: "PATCH", body: JSON.stringify(update) },
    token,
  );

export interface ConversationSummary {
  id: string;
  identity_level: string;
  customer: { name: string; email_masked: string } | null;
  created_at: string;
  last_activity_at: string;
  message_count: number;
  first_message: string | null;
}

export interface ConversationDetail extends Omit<ConversationSummary, "message_count" | "first_message"> {
  linked_via: string | null;
  handoff_status: string;
  handoff_agent_name: string | null;
  messages: {
    seq: number;
    role: string;
    kind: string;
    content: string;
    author_name: string | null;
    created_at: string;
  }[];
  identification: {
    method: string;
    outcome: string;
    reason: string | null;
    email_masked: string | null;
    created_at: string;
  }[];
}

export const listConversations = (token: string, tenantId: string, before?: string) =>
  request<ConversationSummary[]>(
    `/tenants/${tenantId}/conversations${before ? `?before=${encodeURIComponent(before)}` : ""}`,
    {},
    token,
  );

export const readConversation = (token: string, tenantId: string, conversationId: string) =>
  request<ConversationDetail>(`/tenants/${tenantId}/conversations/${conversationId}`, {}, token);

export interface EscalationItem {
  id: string;
  handoff_status: "waiting" | "active";
  agent_name: string | null;
  requested_at: string | null;
  customer: { name: string; email_masked: string } | null;
  ticket: { category: string; subject: string; priority: string } | null;
  last_message: string | null;
}

const inbox = (tenantId: string, conversationId?: string, action?: string) =>
  `/tenants/${tenantId}/escalations${conversationId ? `/${conversationId}/${action}` : ""}`;

export const listEscalations = (token: string, tenantId: string) =>
  request<EscalationItem[]>(inbox(tenantId), {}, token);

export const claimEscalation = (token: string, tenantId: string, conversationId: string) =>
  request<void>(inbox(tenantId, conversationId, "claim"), { method: "POST" }, token);

export const replyToVisitor = (token: string, tenantId: string, conversationId: string, text: string) =>
  request<unknown>(
    inbox(tenantId, conversationId, "messages"),
    { method: "POST", body: JSON.stringify({ text }) },
    token,
  );

export const closeEscalation = (
  token: string,
  tenantId: string,
  conversationId: string,
  notes: string,
) =>
  request<void>(
    inbox(tenantId, conversationId, "close"),
    { method: "POST", body: JSON.stringify({ notes: notes || null }) },
    token,
  );

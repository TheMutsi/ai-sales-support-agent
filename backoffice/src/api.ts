// The admin API (`/api/admin`), typed. Errors carry the backend's `detail.code`, so a page can
// react to "session_expired" or "forbidden" without parsing messages.

export type Role = "viewer" | "agent" | "admin" | "operator";

export interface AdminSession {
  token: string;
  role: Role;
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
  return response.json();
}

export const listLoginOptions = () => request<TenantOption[]>("/login-options");

export const login = (role: Role, tenantId: string | null) =>
  request<AdminSession>("/session", {
    method: "POST",
    body: JSON.stringify({ role, tenant_id: tenantId }),
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
  messages: { seq: number; role: string; kind: string; content: string; created_at: string }[];
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

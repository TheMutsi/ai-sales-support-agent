import { useCallback, useEffect, useState } from "react";
import { ApiError, listTenants, type AdminSession, type TenantOption } from "./api";
import { ConfigPage } from "./ConfigPage";
import { ConversationsPage } from "./ConversationsPage";
import { EscalationsPage } from "./EscalationsPage";
import { LoginPage } from "./LoginPage";
import { loadSession, saveSession } from "./session";

export function App() {
  const [session, setSession] = useState<AdminSession | null>(loadSession);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [page, setPage] = useState<"config" | "conversations" | "escalations">("config");

  const leave = useCallback(() => {
    saveSession(null);
    setSession(null);
    setTenants([]);
    setTenantId(null);
  }, []);

  useEffect(() => {
    if (!session) return;
    listTenants(session.token)
      .then((list) => {
        setTenants(list);
        setTenantId((current) => current ?? list[0]?.id ?? null);
      })
      .catch((error) => {
        if (error instanceof ApiError && error.status === 401) leave();
      });
  }, [session, leave]);

  if (!session) {
    return (
      <LoginPage
        onEnter={(entered) => {
          saveSession(entered);
          setSession(entered);
        }}
      />
    );
  }

  const items = [
    { id: "config" as const, label: "Configuration", icon: "⚙", allowed: true },
    { id: "conversations" as const, label: "Conversations", icon: "💬", allowed: session.permissions.includes("conversations:read") },
    { id: "escalations" as const, label: "Escalations", icon: "🎧", allowed: session.permissions.includes("escalations:read") },
  ].filter((item) => item.allowed);

  return (
    <div className="shell">
      <aside className="sidebar">
        <span className="brand">
          <span className="brand-mark" aria-hidden>M</span>MewFlow
        </span>
        <label className="tenant-pick">
          Tenant
          <select
            value={tenantId ?? ""}
            onChange={(event) => setTenantId(event.target.value)}
            disabled={session.role !== "operator"}
          >
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
        <nav aria-label="Main">
          {items.map((item) => (
            <button
              key={item.id}
              className={page === item.id ? "nav-item active" : "nav-item"}
              aria-current={page === item.id ? "page" : undefined}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon" aria-hidden>{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="user-box">
          <span className="avatar" aria-hidden>{(session.name[0] ?? "?").toUpperCase()}</span>
          <span className="user-info">
            <span className="who">{session.name}</span>
            <span className="role-badge">{session.role}</span>
          </span>
          <button className="ghost" onClick={leave}>Leave</button>
        </div>
      </aside>
      <main className={page === "config" ? undefined : "wide"}>
        {tenantId ? (
          page === "config" ? (
            <ConfigPage key={tenantId} session={session} tenantId={tenantId} onExpired={leave} />
          ) : page === "conversations" ? (
            <ConversationsPage key={tenantId} session={session} tenantId={tenantId} onExpired={leave} />
          ) : (
            <EscalationsPage key={tenantId} session={session} tenantId={tenantId} onExpired={leave} />
          )
        ) : (
          <p>No tenant to show.</p>
        )}
      </main>
    </div>
  );
}

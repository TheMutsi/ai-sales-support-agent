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
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("backoffice:collapsed") === "1";
    } catch {
      return false;
    }
  });
  const [page, setPage] = useState<"config" | "conversations" | "escalations">("config");

  const toggleSidebar = () =>
    setCollapsed((now) => {
      try {
        localStorage.setItem("backoffice:collapsed", now ? "0" : "1");
      } catch {
        /* storage unavailable: it just won't be remembered */
      }
      return !now;
    });

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
    <div className={collapsed ? "shell collapsed" : "shell"}>
      <aside className="sidebar">
        <div className="sidebar-top">
          <span className="brand">
            <span className="brand-mark" aria-hidden>M</span>
            <span className="label">MewFlow</span>
          </span>
          <button
            className="ghost icon-button"
            aria-label={collapsed ? "Expand menu" : "Collapse menu"}
            aria-expanded={!collapsed}
            onClick={toggleSidebar}
          >
            {collapsed ? "»" : "«"}
          </button>
        </div>
        <label className="tenant-pick label">
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
              aria-label={item.label}
              title={item.label}
              onClick={() => setPage(item.id)}
            >
              <span className="nav-icon" aria-hidden>{item.icon}</span>
              <span className="label">{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="user-box">
          <span className="avatar" aria-hidden>{(session.name[0] ?? "?").toUpperCase()}</span>
          <span className="user-info label">
            <span className="who">{session.name}</span>
            <span className="role-badge">{session.role}</span>
          </span>
          <button className="ghost label" onClick={leave}>Leave</button>
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

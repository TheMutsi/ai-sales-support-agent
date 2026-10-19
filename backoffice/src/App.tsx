import { useCallback, useEffect, useState } from "react";
import { ApiError, listTenants, type AdminSession, type TenantOption } from "./api";
import { ConfigPage } from "./ConfigPage";
import { ConversationsPage } from "./ConversationsPage";
import { LoginPage } from "./LoginPage";
import { loadSession, saveSession } from "./session";

export function App() {
  const [session, setSession] = useState<AdminSession | null>(loadSession);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [page, setPage] = useState<"config" | "conversations">("config");

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

  return (
    <div className="shell">
      <header>
        <strong>MewFlow back office</strong>
        <label>
          Tenant{" "}
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
        <span className="role">{session.role}</span>
        <button onClick={leave}>Leave</button>
      </header>
      <nav>
        <button className={page === "config" ? "tab active" : "tab"} onClick={() => setPage("config")}>
          Configuration
        </button>
        {session.permissions.includes("conversations:read") && (
          <button
            className={page === "conversations" ? "tab active" : "tab"}
            onClick={() => setPage("conversations")}
          >
            Conversations
          </button>
        )}
      </nav>
      <main className={page === "conversations" ? "wide" : undefined}>
        {tenantId ? (
          page === "config" ? (
            <ConfigPage key={tenantId} session={session} tenantId={tenantId} onExpired={leave} />
          ) : (
            <ConversationsPage key={tenantId} session={session} tenantId={tenantId} onExpired={leave} />
          )
        ) : (
          <p>No tenant to show.</p>
        )}
      </main>
    </div>
  );
}

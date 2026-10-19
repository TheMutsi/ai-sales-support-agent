import { useEffect, useState } from "react";
import { listLoginOptions, login, type AdminSession, type Role, type TenantOption } from "./api";

const ROLES: Role[] = ["viewer", "agent", "admin", "operator"];

export function LoginPage({ onEnter }: { onEnter: (session: AdminSession) => void }) {
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [role, setRole] = useState<Role>("admin");
  const [tenantId, setTenantId] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listLoginOptions()
      .then((list) => {
        setTenants(list);
        setTenantId(list[0]?.id ?? "");
      })
      .catch(() => setError("The back office API is not reachable. Is it enabled (ADMIN_API_ENABLED)?"));
  }, []);

  const enter = () =>
    login(role, role === "operator" ? null : tenantId, name.trim())
      .then(onEnter)
      .catch(() => setError("Could not enter."));

  return (
    <div className="login">
      <h1>MewFlow back office</h1>
      <p className="pending">
        <strong>Login pending.</strong> There is no authentication yet: pick a role to try the back
        office. This page exists only in local environments.
      </p>
      <label>
        Role
        <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
          {ROLES.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label>
        Your name <span className="hint">(what a visitor sees when you join their chat)</span>
        <input value={name} maxLength={40} onChange={(event) => setName(event.target.value)} />
      </label>
      {role !== "operator" && (
        <label>
          Tenant
          <select value={tenantId} onChange={(event) => setTenantId(event.target.value)}>
            {tenants.map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <button onClick={enter} disabled={role !== "operator" && !tenantId}>
        Enter
      </button>
    </div>
  );
}

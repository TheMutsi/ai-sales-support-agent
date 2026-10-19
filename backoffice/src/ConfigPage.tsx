import { useEffect, useState } from "react";
import { ApiError, readConfig, updateConfig, type AdminSession, type TenantConfig } from "./api";
import { LEVELS, SCOPES, buildOverrides, messageFor, parseOrigins, toggleScope, type Overrides } from "./config";

interface Props {
  session: AdminSession;
  tenantId: string;
  onExpired: () => void;
}

export function ConfigPage({ session, tenantId, onExpired }: Props) {
  const [config, setConfig] = useState<TenantConfig | null>(null);
  const [origins, setOrigins] = useState("");
  const [custom, setCustom] = useState<Overrides>({});
  const [message, setMessage] = useState<string | null>(null);
  const canWrite = session.permissions.includes("config:write");

  const show = (loaded: TenantConfig) => {
    setConfig(loaded);
    setOrigins(loaded.allowed_origins.join("\n"));
    setCustom(loaded.scope_overrides ?? {});
  };
  const fail = (error: unknown) => {
    if (error instanceof ApiError && error.status === 401) return onExpired();
    setMessage(error instanceof ApiError ? messageFor(error.status, error.code) : "Request failed.");
  };

  useEffect(() => {
    readConfig(session.token, tenantId).then(show).catch(fail);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.token, tenantId]);

  const save = () =>
    updateConfig(session.token, tenantId, {
      allowed_origins: parseOrigins(origins),
      scope_overrides: buildOverrides(custom),
    })
      .then((saved) => {
        show(saved);
        setMessage("Saved. The API sees it now on this instance and within a minute on others.");
      })
      .catch(fail);

  if (!config) return <p>{message ?? "Loading…"}</p>;

  return (
    <section>
      <h2>{config.name}: configuration</h2>
      <div className="card">
      <h3>Allowed origins</h3>
      <p className="hint">The pages the widget may run on, one per line (https://shop.example).</p>
      <textarea rows={5} value={origins} onChange={(e) => setOrigins(e.target.value)} disabled={!canWrite} />
      </div>
      <div className="card">
      <h3>What each identity level may do</h3>
      <p className="hint">Unchecked "customise" keeps the defaults.</p>
      {LEVELS.map((level) => (
        <fieldset key={level} disabled={!canWrite}>
          <legend>
            <label>
              <input
                type="checkbox"
                checked={level in custom}
                onChange={(e) =>
                  setCustom((now) => {
                    const { [level]: _dropped, ...rest } = now;
                    return e.target.checked ? { ...rest, [level]: ["kb:read"] } : rest;
                  })
                }
              />{" "}
              {level}: customise
            </label>
          </legend>
          {level in custom && (
            <div className="scopes">
            {SCOPES.map((scope) => (
              <label key={scope} className="scope">
                <input
                  type="checkbox"
                  checked={custom[level].includes(scope)}
                  onChange={() => setCustom((now) => ({ ...now, [level]: toggleScope(now[level], scope) }))}
                />{" "}
                {scope}
              </label>
            ))}
            </div>
          )}
        </fieldset>
      ))}
      </div>
      <div className="actions">
        <button className="primary" onClick={save} disabled={!canWrite}>
          Save
        </button>
        {message && <p role="status" className="saved">{message}</p>}
        {!canWrite && <span className="hint">Your role cannot change the configuration.</span>}
      </div>
    </section>
  );
}

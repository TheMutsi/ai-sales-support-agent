import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  claimEscalation,
  closeEscalation,
  listEscalations,
  readConversation,
  replyToVisitor,
  resolveEscalation,
  type AdminSession,
  type ConversationDetail,
  type EscalationFilters,
  type EscalationItem,
} from "./api";
import { messageFor } from "./config";
import { who } from "./conversations";
import { reasonLine, speaker, splitList, waitingLine } from "./escalations";

const POLL_MS = 4000;

interface Props {
  session: AdminSession;
  tenantId: string;
  onExpired: () => void;
}

export function EscalationsPage({ session, tenantId, onExpired }: Props) {
  const [items, setItems] = useState<EscalationItem[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [text, setText] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ q: "", tags: "", properties: "", route: "", status: "open" });
  const [filters, setFilters] = useState<EscalationFilters>({ status: "open" });
  const latest = useRef(0);
  const canAct = session.permissions.includes("escalations:reply");

  const fail = useCallback(
    (failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 401) return onExpired();
      setError(failure instanceof ApiError ? messageFor(failure.status, failure.code) : "Could not load this.");
    },
    [onExpired],
  );

  const refresh = useCallback(() => {
    listEscalations(session.token, tenantId, filters)
      .then((loaded) => {
        setItems(loaded);
        setError(null);
      })
      .catch(fail);
    if (!selected) return;
    const mine = ++latest.current;
    readConversation(session.token, tenantId, selected)
      .then((loaded) => mine === latest.current && setDetail(loaded))
      .catch(fail);
  }, [session.token, tenantId, selected, filters, fail]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const act = (call: Promise<unknown>, after?: () => void) =>
    call
      .then(() => {
        setError(null);
        after?.();
        refresh();
      })
      .catch(fail);

  const search = (event: React.FormEvent) => {
    event.preventDefault();
    setFilters({
      status: form.status as EscalationFilters["status"],
      route: (form.route || undefined) as EscalationFilters["route"],
      q: form.q,
      tags: splitList(form.tags),
      properties: splitList(form.properties),
    });
  };

  const open = (id: string) => {
    setDetail(null);
    setText("");
    setNotes("");
    setSelected(id);
  };

  if (!items) return <p>{error ?? "Loading…"}</p>;
  const active = detail?.handoff_status === "active";
  const selectedItem = items.find((item) => item.id === selected);
  const offlineOpen = detail?.escalation_status === "open" && detail.handoff_status === "none";
  const waiting = detail?.handoff_status === "waiting";

  return (
    <section className="conversations agent-view">
      <div className="list">
        <h2>Escalations</h2>
        <form className="filters" onSubmit={search}>
          <input
            value={form.q}
            onChange={(event) => setForm({ ...form, q: event.target.value })}
            placeholder="Search a number, customer or message"
            aria-label="Search"
          />
          <input
            value={form.tags}
            onChange={(event) => setForm({ ...form, tags: event.target.value })}
            placeholder="Tags: vip, black-friday"
            aria-label="Tags"
          />
          <input
            value={form.properties}
            onChange={(event) => setForm({ ...form, properties: event.target.value })}
            placeholder="Info: device:iphone"
            aria-label="Info"
          />
          <div className="reply">
            <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })} aria-label="Status">
              <option value="open">Open</option>
              <option value="resolved">Resolved</option>
              <option value="all">All</option>
            </select>
            <select value={form.route} onChange={(event) => setForm({ ...form, route: event.target.value })} aria-label="Kind">
              <option value="">Live and offline</option>
              <option value="live">Live</option>
              <option value="offline">Offline</option>
            </select>
            <button className="primary" type="submit">Search</button>
          </div>
        </form>
        {error && <p className="error">{error}</p>}
        {items.length === 0 && <p className="hint">Nothing matches.</p>}
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button
                className={selected === item.id ? "item active" : "item"}
                data-state={item.status === "resolved" ? "resolved" : item.handoff_status}
                onClick={() => open(item.id)}
              >
                <strong>{who(item)}</strong>
                <span className="hint">
                  {item.reference} · {item.route === "live" ? "Live" : "Offline"} · {waitingLine(item)}
                </span>
                {item.tags.length > 0 && <span className="hint">{item.tags.join(", ")}</span>}
                <span className="hint">{item.last_message}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="detail">
        {detail ? (
          <>
            <div className="detail-head">
              <h3>{who(detail)}</h3>
              {(waiting || active) && (
                <span className={`chip ${detail.handoff_status}`}>
                  {waiting ? "Waiting" : `With ${detail.handoff_agent_name ?? "an agent"}`}
                </span>
              )}
              {detail.escalation_reference && (
                <span className="chip">
                  {detail.escalation_reference} · {detail.escalation_route} · {detail.escalation_status}
                </span>
              )}
            </div>
            {selectedItem && reasonLine(selectedItem.reason) && <p className="hint">{reasonLine(selectedItem.reason)}</p>}
            {Object.keys(detail.properties).length > 0 && (
              <p className="hint">
                {Object.entries(detail.properties).map(([key, value]) => `${key}: ${value}`).join(" · ")}
              </p>
            )}
            {detail.escalation_notes && <p className="hint">Notes: {detail.escalation_notes}</p>}
            {detail.messages.map((message) => (
              <p key={message.seq} className={`message ${message.role}`}>
                <span className="hint">{speaker(message)}</span>
                {message.content}
              </p>
            ))}
            {waiting && canAct && (
              <button className="primary" onClick={() => act(claimEscalation(session.token, tenantId, detail.id))}>
                Join the chat as {session.name}
              </button>
            )}
            {active && canAct && (
              <>
                <form
                  className="reply"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (text.trim()) act(replyToVisitor(session.token, tenantId, detail.id, text.trim()), () => setText(""));
                  }}
                >
                  <input value={text} onChange={(event) => setText(event.target.value)} placeholder="Write to the visitor" />
                  <button className="primary" type="submit">Send</button>
                </form>
                <div className="reply">
                  <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Resolution notes (optional)" />
                  <button
                    onClick={() =>
                      act(closeEscalation(session.token, tenantId, detail.id, notes), () => setNotes(""))
                    }
                  >
                    Close and hand back to the assistant
                  </button>
                </div>
              </>
            )}
            {offlineOpen && canAct && (
              <div className="reply">
                <input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="What was done (optional)" />
                <button
                  className="primary"
                  onClick={() => act(resolveEscalation(session.token, tenantId, detail.id, notes), () => setNotes(""))}
                >
                  Mark as resolved
                </button>
              </div>
            )}
            {!canAct && <p className="hint">Your role can read escalations but not answer them.</p>}
          </>
        ) : (
          <p className="hint">{selected ? "Loading…" : "Pick an escalation."}</p>
        )}
      </div>
    </section>
  );
}

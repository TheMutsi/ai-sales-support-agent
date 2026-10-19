import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  claimEscalation,
  closeEscalation,
  listEscalations,
  readConversation,
  replyToVisitor,
  type AdminSession,
  type ConversationDetail,
  type EscalationItem,
} from "./api";
import { messageFor } from "./config";
import { who } from "./conversations";
import { speaker, waitingLine } from "./escalations";

const POLL_MS = 4000; // the visitor's widget polls too; a few seconds is enough for a chat

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
  const latest = useRef(0); // only the newest detail request may update the screen
  const canAct = session.permissions.includes("escalations:reply");

  const fail = useCallback(
    (failure: unknown) => {
      if (failure instanceof ApiError && failure.status === 401) return onExpired();
      setError(failure instanceof ApiError ? messageFor(failure.status, failure.code) : "Could not load this.");
    },
    [onExpired],
  );

  const refresh = useCallback(() => {
    listEscalations(session.token, tenantId)
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
  }, [session.token, tenantId, selected, fail]);

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

  const open = (id: string) => {
    setDetail(null);
    setText("");
    setNotes("");
    setSelected(id);
  };

  if (!items) return <p>{error ?? "Loading…"}</p>;
  const active = detail?.handoff_status === "active";
  const waiting = detail?.handoff_status === "waiting";

  return (
    <section className="conversations agent-view">
      <div className="list">
        <h2>Escalations</h2>
        {error && <p className="error">{error}</p>}
        {items.length === 0 && <p className="hint">Nobody is waiting for a person.</p>}
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button
                className={selected === item.id ? "item active" : "item"}
                data-state={item.handoff_status}
                onClick={() => open(item.id)}
              >
                <strong>{who(item)}</strong>
                <span className="hint">{waitingLine(item)}</span>
                <span>{item.ticket?.subject}</span>
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
              <span className={`chip ${detail.handoff_status}`}>{waiting ? "Waiting" : active ? `With ${detail.handoff_agent_name ?? "an agent"}` : detail.handoff_status}</span>
            </div>
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
            {!canAct && <p className="hint">Your role can read escalations but not answer them.</p>}
          </>
        ) : (
          <p className="hint">{selected ? "Loading…" : "Pick an escalation."}</p>
        )}
      </div>
    </section>
  );
}

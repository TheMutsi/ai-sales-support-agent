import { useEffect, useState } from "react";
import {
  ApiError,
  listConversations,
  readConversation,
  type AdminSession,
  type ConversationDetail,
  type ConversationSummary,
} from "./api";
import { identificationLine, nextCursor, who } from "./conversations";

interface Props {
  session: AdminSession;
  tenantId: string;
  onExpired: () => void;
}

export function ConversationsPage({ session, tenantId, onExpired }: Props) {
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [selected, setSelected] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fail = (failure: unknown) => {
    if (failure instanceof ApiError && failure.status === 401) return onExpired();
    setError("Could not load this. Try again.");
  };

  const load = (before?: string) =>
    listConversations(session.token, tenantId, before)
      .then((page) => setItems((now) => [...(before ? (now ?? []) : []), ...page]))
      .catch(fail);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.token, tenantId]);

  const open = (id: string) =>
    readConversation(session.token, tenantId, id)
      .then((detail) => {
        setError(null);
        setSelected(detail);
      })
      .catch(fail);

  if (!items) return <p>{error ?? "Loading…"}</p>;
  const cursor = nextCursor(items);

  return (
    <section className="conversations">
      <div className="list">
        <h2>Conversations</h2>
        {error && <p className="error">{error}</p>}
        {items.length === 0 && <p className="hint">No conversations yet.</p>}
        <ul>
          {items.map((item) => (
            <li key={item.id}>
              <button
                className={selected?.id === item.id ? "item active" : "item"}
                onClick={() => open(item.id)}
              >
                <strong>{who(item)}</strong>
                <span className="hint">
                  {new Date(item.last_activity_at).toLocaleString()} · {item.message_count} messages ·{" "}
                  {item.identity_level}
                </span>
                <span>{item.first_message}</span>
              </button>
            </li>
          ))}
        </ul>
        {cursor && <button onClick={() => load(cursor)}>Older conversations</button>}
      </div>
      <div className="detail">
        {selected ? (
          <>
            <div className="detail-head">
              <h3>{who(selected)}</h3>
              <span className="chip">{selected.identity_level}</span>
            </div>
            {selected.identification.length > 0 && (
              <ol className="timeline">
                {selected.identification.map((event) => (
                  <li key={event.created_at + event.method}>
                    {new Date(event.created_at).toLocaleTimeString()}: {identificationLine(event)}
                  </li>
                ))}
              </ol>
            )}
            {selected.messages.map((message) => (
              <p key={message.seq} className={`message ${message.role}`}>
                <span className="hint">
                  {message.role}
                  {message.kind !== "text" && ` · ${message.kind}`}
                </span>
                {message.content}
              </p>
            ))}
          </>
        ) : (
          <p className="hint">Pick a conversation.</p>
        )}
      </div>
    </section>
  );
}

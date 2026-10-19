import type { ChatEvent, ChatMessage, Handoff } from "./types";

export interface ChatState {
  messages: ChatMessage[];
  /** A turn is in flight: the input should wait. */
  streaming: boolean;
  error: string | null;
  /** The assistant asked the visitor to identify; `methods` are the ways to offer (empty: only the shop's own login). */
  identity: { methods: string[] } | null;
  /** A person has the conversation: the widget polls for what they write. */
  handoff: Handoff;
}

export const initialState: ChatState = { messages: [], streaming: false, error: null, identity: null, handoff: "none" };

/** Id of the assistant message being written by the current turn. */
export const STREAMING_ID = "streaming";

function setAnswer(state: ChatState, text: string): ChatState {
  const index = state.messages.findIndex((m) => m.id === STREAMING_ID);
  const answer: ChatMessage = { id: STREAMING_ID, role: "assistant", kind: "text", content: text };
  const messages = [...state.messages];
  if (index >= 0) messages[index] = { ...messages[index], content: text };
  else messages.push(answer);
  return { ...state, messages };
}

/**
 * How one server event changes the conversation. `delta` appends live text; `reset` drops text
 * the model said before searching the knowledge base; `message` and `correction` carry the final
 * text (a guardrail may have rewritten what was streamed), so they replace rather than append.
 */
export function applyEvent(state: ChatState, event: ChatEvent): ChatState {
  switch (event.event) {
    case "delta": {
      const current = state.messages.find((m) => m.id === STREAMING_ID)?.content ?? "";
      return setAnswer(state, current + event.data.text);
    }
    case "reset":
      return setAnswer(state, "");
    case "message":
    case "correction":
      return setAnswer(state, event.data.text);
    case "error":
      return { ...state, streaming: false, error: event.data.message ?? "The assistant could not answer." };
    case "done": {
      const finished = state.messages.filter((m) => m.id !== STREAMING_ID || m.content !== "");
      const kind: ChatMessage["kind"] = event.data.identity_required ? "identity_request" : "text";
      const cards = event.data.cards?.length ? event.data.cards : undefined;
      const messages = finished.map((m) =>
        m.id === STREAMING_ID ? { ...m, id: `answer-${finished.length}`, kind, cards } : m,
      );
      return {
        ...state,
        messages,
        streaming: false,
        identity: event.data.identity_required ? { methods: event.data.identity_methods } : null,
        // A turn that opened a ticket leaves the conversation waiting for a person (the server
        // decided that when it saved the reply).
        handoff: event.data.handoff ?? (event.data.ticket_created ? "waiting" : state.handoff),
      };
    }
  }
}

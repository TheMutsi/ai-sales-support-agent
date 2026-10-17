import type { ChatEvent, ChatMessage } from "./types";

export interface ChatState {
  messages: ChatMessage[];
  /** A turn is in flight: the input should wait. */
  streaming: boolean;
  error: string | null;
  /** The assistant asked the visitor to identify; these are the methods to offer. */
  identityMethods: string[];
}

export const initialState: ChatState = { messages: [], streaming: false, error: null, identityMethods: [] };

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
      const messages = finished.map((m) => (m.id === STREAMING_ID ? { ...m, id: `answer-${finished.length}` } : m));
      return {
        ...state,
        messages,
        streaming: false,
        identityMethods: event.data.identity_required ? event.data.identity_methods : [],
      };
    }
  }
}

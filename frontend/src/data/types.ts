/** Wire and view types shared by the data layer. Field names follow the backend's JSON. */

export interface Session {
  token: string;
  conversationId: string;
  expiresAt: string;
  identityLevel: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  kind: "text" | "identity_request";
  content: string;
  /** Previews of images the visitor attached. Local only: they are not sent or stored yet. */
  images?: { url: string; alt: string }[];
}

export interface TurnSummary {
  identity_required: boolean;
  identity_methods: string[];
}

/** One server-sent event of a chat turn (see `app/api/chat.py`). */
export type ChatEvent =
  | { event: "delta"; data: { text: string } }
  | { event: "reset"; data: Record<string, never> }
  | { event: "message"; data: { text: string } }
  | { event: "correction"; data: { text: string } }
  | { event: "error"; data: { message?: string } }
  | { event: "done"; data: TurnSummary };

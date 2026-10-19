/** Wire and view types shared by the data layer. Field names follow the backend's JSON. */

export interface Session {
  token: string;
  conversationId: string;
  expiresAt: string;
  identityLevel: string;
}

/** Whether a person has taken the conversation from the assistant. */
export type Handoff = "none" | "waiting" | "active";

export interface CardImage {
  url: string;
  alt: string;
}

/** Things a reply can show next to its text (see `app/schemas/cards.py`). */
export type Card =
  | { type: "action"; id: string; title: string; subtitle?: string | null; badge?: string | null; message: string }
  | { type: "product"; id: string; name: string; subtitle?: string | null; price?: string | null; badge?: string | null; image: CardImage }
  | { type: "coupon"; id: string; code: string; title: string; subtitle?: string | null };

export interface ChatMessage {
  id: string;
  /** `human` is a person from the shop's back office; `system` is a notice ("an agent joined"). */
  role: "user" | "assistant" | "human" | "system";
  kind: "text" | "identity_request" | "system";
  content: string;
  /** The name a person's message is shown under. */
  author?: string;
  /** Previews of images the visitor attached. Local only: they are not sent or stored yet. */
  images?: { url: string; alt: string }[];
  /** Offers to pick, products to look at: drawn under the text of an assistant message. */
  cards?: Card[];
}

export interface TurnSummary {
  identity_required: boolean;
  identity_methods: string[];
  ticket_created?: boolean;
  /** Set when a person has the conversation: the message was stored and nobody answers it live. */
  handoff?: "waiting" | "active" | null;
  cards?: Card[];
}

/** One server-sent event of a chat turn (see `app/api/chat.py`). */
export type ChatEvent =
  | { event: "delta"; data: { text: string } }
  | { event: "reset"; data: Record<string, never> }
  | { event: "message"; data: { text: string } }
  | { event: "correction"; data: { text: string } }
  | { event: "error"; data: { message?: string } }
  | { event: "done"; data: TurnSummary };

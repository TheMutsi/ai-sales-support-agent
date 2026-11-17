export interface Session {
  token: string;
  conversationId: string;
  expiresAt: string;
  identityLevel: string;
}

export type Handoff = "none" | "waiting" | "active";

export interface CardImage {
  url: string;
  alt: string;
}

export type Card =
  | { type: "action"; id: string; title: string; subtitle?: string | null; badge?: string | null; message: string; action?: string | null; order_id?: string | null }
  | {
      type: "product";
      id: string;
      name: string;
      subtitle?: string | null;
      price?: string | null;
      compare_price?: string | null;
      badge?: string | null;
      image: CardImage;
      more_images?: CardImage[];
    }
  | { type: "divider"; id: string; label?: string }
  | {
      type: "recommendation";
      id: string;
      template: "product_card";
      title: string;
      description?: string | null;
      image: CardImage;
      rating?: number | null;
      url?: string | null;
      price?: string | null;
      compare_price?: string | null;
      offer_label?: string | null;
      why?: string | null;
    };

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "human" | "system";
  kind: "text" | "identity_request" | "system";
  content: string;
  author?: string;
  images?: { url: string; alt: string }[];
  cards?: Card[];
}

export interface TurnSummary {
  identity_required: boolean;
  identity_methods: string[];
  ticket_created?: boolean;
  escalation_route?: "live" | "offline" | null;
  escalation_reference?: string | null;
  handoff?: "waiting" | "active" | null;
  cards?: Card[];
}

export type ChatEvent =
  | { event: "delta"; data: { text: string } }
  | { event: "reset"; data: Record<string, never> }
  | { event: "message"; data: { text: string } }
  | { event: "correction"; data: { text: string } }
  | { event: "error"; data: { message?: string } }
  | { event: "done"; data: TurnSummary };

export type ChatInput =
  | { type: "text"; message: string }
  | { type: "action"; action: string; order_id?: string | null };

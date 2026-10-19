import { parseSse } from "./sse";
import type { Card, ChatEvent, ChatMessage, Handoff, Session } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(`${status} ${code}`);
  }
}

interface SessionJson {
  session_token: string;
  conversation_id: string;
  expires_at: string;
  identity_level: string;
}

const toSession = (json: SessionJson): Session => ({
  token: json.session_token,
  conversationId: json.conversation_id,
  expiresAt: json.expires_at,
  identityLevel: json.identity_level,
});

export function createApi(baseUrl: string, apiKey: string, fetchFn: typeof fetch = fetch) {
  /** A picture on our API comes as a path; the widget lives on the shop's page, so make it absolute. */
  const safeUrl = (url: string): string => {
    const absolute = url.startsWith("/") ? `${baseUrl}${url}` : url;
    return /^https?:\/\//i.test(absolute) ? absolute : ""; // a picture is only ever http(s)
  };
  const resolveCards = (cards: Card[] | undefined): Card[] | undefined =>
    cards?.map((card) =>
      card.type === "product"
        ? {
            ...card,
            image: { ...card.image, url: safeUrl(card.image.url) },
            more_images: card.more_images?.map((image) => ({ ...image, url: safeUrl(image.url) })),
          }
        : card,
    );

  async function request(path: string, init: { method?: "GET" | "POST"; body?: unknown; token?: string; signal?: AbortSignal } = {}) {
    const headers: Record<string, string> = {};
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    if (init.token) headers.Authorization = `Bearer ${init.token}`;
    const response = await fetchFn(`${baseUrl}/api${path}`, {
      method: init.method ?? "POST",
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: init.signal,
    });
    if (!response.ok) {
      const detail = await response.json().then((j) => j?.detail, () => undefined);
      throw new ApiError(response.status, detail?.code ?? "unknown");
    }
    return response;
  }

  async function* withCards(events: AsyncGenerator<ChatEvent>): AsyncGenerator<ChatEvent> {
    for await (const event of events) {
      yield event.event === "done" && event.data.cards
        ? { ...event, data: { ...event.data, cards: resolveCards(event.data.cards) } }
        : event;
    }
  }

  return {
    async startConversation(): Promise<Session> {
      return toSession(await (await request("/conversations", { body: { api_key: apiKey } })).json());
    },

    /** Exchanges the shop's signed token for a session; `current` keeps an ongoing conversation. */
    async login(token: string, current?: string): Promise<Session> {
      const response = await request("/auth/login", { body: { api_key: apiKey, token }, token: current });
      return toSession(await response.json());
    },

    /** Emails a code. Always the same empty 202, whether or not the address is a customer. */
    async requestOtp(email: string, current?: string): Promise<void> {
      await request("/auth/otp/request", { body: { api_key: apiKey, email }, token: current });
    },

    /** Checks the code on the server (it never passes through the chat) and upgrades the session. */
    async verifyOtp(email: string, code: string, current?: string): Promise<Session> {
      const response = await request("/auth/otp/verify", { body: { api_key: apiKey, email, code }, token: current });
      return toSession(await response.json());
    },

    /**
     * A weaker proof than a code: an email and one of its orders. The session it gives can read
     * that order and nothing about the customer. Any mismatch is the same generic 401.
     */
    async orderLookup(email: string, orderId: string, current?: string): Promise<Session> {
      const response = await request("/auth/order-lookup", {
        body: { api_key: apiKey, email, order_id: orderId },
        token: current,
      });
      return toSession(await response.json());
    },

    async messages(session: Session): Promise<{ messages: ChatMessage[]; handoff: Handoff }> {
      const response = await request(`/conversations/${session.conversationId}/messages`, {
        method: "GET",
        token: session.token,
      });
      const { messages, handoff } = await response.json();
      type Stored = { seq: number; role: ChatMessage["role"]; kind: ChatMessage["kind"]; content: string; author_name?: string | null; cards?: Card[] };
      return {
        messages: messages.map((m: Stored) => ({
          id: `seq-${m.seq}`,
          role: m.role,
          kind: m.kind,
          content: m.content,
          author: m.author_name ?? undefined,
          cards: m.cards?.length ? resolveCards(m.cards) : undefined,
        })),
        handoff: handoff ?? "none",
      };
    },

    /** One chat turn. `messageId` makes a retry replay the stored answer instead of running twice. */
    async *chat(session: Session, message: string, messageId: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
      const response = await request("/chat", { body: { message, message_id: messageId }, token: session.token, signal });
      yield* withCards(parseSse(response.body!));
    },

    async *resume(session: Session, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
      const response = await request("/chat/resume", { body: {}, token: session.token, signal });
      yield* withCards(parseSse(response.body!));
    },
  };
}

export type Api = ReturnType<typeof createApi>;

import { parseSse } from "./sse";
import type { ChatEvent, ChatMessage, Session } from "./types";

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

    async messages(session: Session): Promise<ChatMessage[]> {
      const response = await request(`/conversations/${session.conversationId}/messages`, {
        method: "GET",
        token: session.token,
      });
      const { messages } = await response.json();
      return messages.map((m: { seq: number; role: ChatMessage["role"]; kind: ChatMessage["kind"]; content: string }) => ({
        id: `seq-${m.seq}`,
        role: m.role,
        kind: m.kind,
        content: m.content,
      }));
    },

    /** One chat turn. `messageId` makes a retry replay the stored answer instead of running twice. */
    async *chat(session: Session, message: string, messageId: string, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
      const response = await request("/chat", { body: { message, message_id: messageId }, token: session.token, signal });
      yield* parseSse(response.body!);
    },

    async *resume(session: Session, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
      const response = await request("/chat/resume", { body: {}, token: session.token, signal });
      yield* parseSse(response.body!);
    },
  };
}

export type Api = ReturnType<typeof createApi>;

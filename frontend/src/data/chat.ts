import { ApiError, type Api } from "./api";
import type { Auth } from "./auth";
import { applyEvent, initialState, type ChatState } from "./chatState";
import type { Context } from "./context";
import type { SessionStore } from "./sessionStore";
import type { Card, ChatEvent, ChatInput, ChatMessage, Session } from "./types";

export function createChat(api: Api, auth: Auth, store: SessionStore, context?: Context) {
  let state: ChatState = initialState;
  let newest = 0;
  const listeners = new Set<() => void>();
  const update = (next: ChatState) => {
    state = next;
    listeners.forEach((listener) => listener());
  };

  async function withSession<T>(work: (session: Session) => Promise<T>): Promise<T> {
    try {
      return await work(await auth.ensure());
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) return work(await auth.renew());
      throw error;
    }
  }

  async function run(open: (session: Session) => AsyncGenerator<ChatEvent>) {
    update({ ...state, streaming: true, error: null, identity: null });
    try {
      await withSession(async (session) => {
        await context?.sync(session);
        for await (const event of open(session)) update(applyEvent(state, event));
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        update({ ...state, streaming: false, error: null, broken: true });
        return;
      }
      const busy = error instanceof ApiError && error.code === "turn_in_progress";
      update({ ...state, streaming: false, error: busy ? "Still answering your last message." : "Could not reach the assistant." });
    }
  }

  return {
    getState: () => state,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async load() {
      try {
        const { messages, handoff } = await withSession((session) => api.messages(session));
        const pending = messages.at(-1)?.kind === "identity_request";
        update({ ...state, messages, handoff, error: null, identity: pending ? { methods: ["otp", "order_id"] } : null });
      } catch {
        update({ ...state, error: "Could not load the conversation." });
      }
    },
    async refresh() {
      const session = auth.current();
      if (state.streaming || !session) return;
      const mine = ++newest;
      try {
        const { messages, handoff } = await api.messages(session);
        if (state.streaming || mine !== newest) return;
        update({ ...state, messages: keepImages(messages, state.messages), handoff });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && mine === newest && !state.streaming) {
          update({ ...state, error: "Your session expired. Send a message to continue." });
        }
      }
    },
    async send(text: string, images: ChatMessage["images"] = []) {
      if (state.streaming || !text.trim()) return;
      const id = crypto.randomUUID();
      store.touch();
      update({ ...state, messages: [...state.messages, { id, role: "user", kind: "text", content: text, images }] });
      await run((session) => api.chat(session, { type: "text", message: text }, id));
    },
    async pick(card: Extract<Card, { type: "action" }>) {
      if (!card.action) return this.send(card.message);
      if (state.streaming) return;
      const id = crypto.randomUUID();
      const input: ChatInput = { type: "action", action: card.action, order_id: card.order_id ?? null };
      store.touch();
      update({ ...state, messages: [...state.messages, { id, role: "user", kind: "text", content: card.message }] });
      await run((session) => api.chat(session, input, id));
    },
    restart() {
      store.clear();
      update(initialState);
    },
    async resume() {
      await run((session) => api.resume(session));
    },
  };
}

function keepImages(fromServer: ChatMessage[], local: ChatMessage[]): ChatMessage[] {
  const previews = local.filter((m) => m.role === "user").map((m) => m.images);
  let visitorMessage = 0;
  return fromServer.map((m) => (m.role === "user" ? { ...m, images: previews[visitorMessage++] } : m));
}

export type Chat = ReturnType<typeof createChat>;

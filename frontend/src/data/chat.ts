import { ApiError, type Api } from "./api";
import type { Auth } from "./auth";
import { applyEvent, initialState, type ChatState } from "./chatState";
import type { SessionStore } from "./sessionStore";
import type { ChatEvent, ChatMessage, Session } from "./types";

/**
 * The conversation as the UI sees it: state to subscribe to (`useSyncExternalStore`) and the
 * actions `load`, `send` and `resume`. The history lives on the server; this only mirrors it.
 */
export function createChat(api: Api, auth: Auth, store: SessionStore) {
  let state: ChatState = initialState;
  let newest = 0; // the latest background poll
  const listeners = new Set<() => void>();
  const update = (next: ChatState) => {
    state = next;
    listeners.forEach((listener) => listener());
  };

  /** Runs `work` with a session, getting a new one once if the server rejects it. */
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
      // The turn is only opened once the first event arrives, so a rejected session throws before
      // any text is shown and the retry in `withSession` is safe.
      await withSession(async (session) => {
        for await (const event of open(session)) update(applyEvent(state, event));
      });
    } catch (error) {
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
    /** Shows the stored conversation (after a reload, or when another tab changed it). */
    async load() {
      try {
        const { messages, handoff } = await withSession((session) => api.messages(session));
        // The stored request does not say which methods it offered, so a reload offers both: the
        // server decides what a proof is worth, and a method the tenant removed just fails.
        const pending = messages.at(-1)?.kind === "identity_request";
        update({ ...state, messages, handoff, error: null, identity: pending ? { methods: ["otp", "order_id"] } : null });
      } catch {
        update({ ...state, error: "Could not load the conversation." });
      }
    },
    /**
     * While a person has the conversation: reads what they wrote. Background work, so it never
     * starts a conversation or renews a session (that would fork the visitor away from the person
     * they are talking to), shows an error only for a rejected session, and never runs during a
     * turn, which owns the messages until it ends.
     */
    async refresh() {
      const session = auth.current();
      if (state.streaming || !session) return;
      const mine = ++newest; // only the newest poll may change the screen
      try {
        const { messages, handoff } = await api.messages(session);
        if (state.streaming || mine !== newest) return;
        update({ ...state, messages: keepImages(messages, state.messages), handoff });
      } catch (error) {
        // A rejected session will not come back by polling: say so once, and send() renews it.
        if (error instanceof ApiError && error.status === 401 && mine === newest && !state.streaming) {
          update({ ...state, error: "Your session expired. Send a message to continue." });
        }
        // Anything else: the next poll tries again.
      }
    },
    async send(text: string, images: ChatMessage["images"] = []) {
      if (state.streaming || !text.trim()) return;
      const id = crypto.randomUUID();
      store.touch();
      update({ ...state, messages: [...state.messages, { id, role: "user", kind: "text", content: text, images }] });
      await run((session) => api.chat(session, text, id));
    },
    /** After the visitor identified: answers the message that was waiting. */
    async resume() {
      await run((session) => api.resume(session));
    },
  };
}

/** The server does not keep image previews, so the visitor's own ones are carried over by order. */
function keepImages(fromServer: ChatMessage[], local: ChatMessage[]): ChatMessage[] {
  const previews = local.filter((m) => m.role === "user").map((m) => m.images);
  let visitorMessage = 0;
  return fromServer.map((m) => (m.role === "user" ? { ...m, images: previews[visitorMessage++] } : m));
}

export type Chat = ReturnType<typeof createChat>;

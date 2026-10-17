import { ApiError, type Api } from "./api";
import type { Auth } from "./auth";
import { applyEvent, initialState, type ChatState } from "./chatState";
import type { SessionStore } from "./sessionStore";
import type { ChatEvent, Session } from "./types";

/**
 * The conversation as the UI sees it: state to subscribe to (`useSyncExternalStore`) and the
 * actions `load`, `send` and `resume`. The history lives on the server; this only mirrors it.
 */
export function createChat(api: Api, auth: Auth, store: SessionStore) {
  let state: ChatState = initialState;
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
    update({ ...state, streaming: true, error: null, identityMethods: [] });
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
        const messages = await withSession((session) => api.messages(session));
        update({ ...state, messages, error: null });
      } catch {
        update({ ...state, error: "Could not load the conversation." });
      }
    },
    async send(text: string) {
      if (state.streaming || !text.trim()) return;
      const id = crypto.randomUUID();
      store.touch();
      update({ ...state, messages: [...state.messages, { id, role: "user", kind: "text", content: text }] });
      await run((session) => api.chat(session, text, id));
    },
    /** After the visitor identified: answers the message that was waiting. */
    async resume() {
      await run((session) => api.resume(session));
    },
  };
}

export type Chat = ReturnType<typeof createChat>;

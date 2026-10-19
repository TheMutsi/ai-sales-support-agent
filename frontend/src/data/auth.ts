import type { Api } from "./api";
import type { SessionStore } from "./sessionStore";
import type { Session } from "./types";

/** The shop's callback returning a freshly signed token for its logged-in customer, or null. */
export type GetToken = () => Promise<string | null> | string | null;

/**
 * Decides which session to use. An existing one wins; otherwise a logged-in shop customer is
 * exchanged for one via `getToken`, and everyone else gets an anonymous conversation. The
 * token is short-lived, so `getToken` is asked again whenever a new session is needed, not once.
 */
export function createAuth(api: Api, store: SessionStore) {
  let getToken: GetToken | null = null;
  let pending: Promise<Session> | null = null;

  async function create(current?: string): Promise<Session> {
    const token = getToken ? await getToken() : null;
    const session = token ? await api.login(token, current) : await api.startConversation();
    store.save(session);
    return session;
  }

  // Concurrent callers (two tabs mounting, a retry racing a load) share one request.
  const once = (work: () => Promise<Session>) => (pending ??= work().finally(() => (pending = null)));

  return {
    currentToken: () => store.load()?.token,
    /** The saved session if it is still valid; never creates one (a background poll must not). */
    current: (): Session | null => store.load(),
    /** Uses a session obtained elsewhere (the one-time code login). */
    adopt: (session: Session) => store.save(session),
    setGetToken: (callback: GetToken | null) => (getToken = callback),
    ensure: (): Promise<Session> => {
      const saved = store.load();
      return saved ? Promise.resolve(saved) : once(() => create());
    },
    /** The server rejected the session: drop it and get a new one. */
    renew: () => once(() => (store.clear(), create())),
    /** The visitor just logged in on the shop's page: upgrade the session, keeping the conversation. */
    identify: () => once(() => create(store.load()?.token)),
  };
}

export type Auth = ReturnType<typeof createAuth>;

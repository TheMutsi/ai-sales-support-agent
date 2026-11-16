import type { Api } from "./api";
import type { SessionStore } from "./sessionStore";
import type { Session } from "./types";

export type GetToken = () => Promise<string | null> | string | null;

export function createAuth(api: Api, store: SessionStore) {
  let getToken: GetToken | null = null;
  let pending: Promise<Session> | null = null;

  async function create(current?: string): Promise<Session> {
    const token = getToken ? await getToken() : null;
    const session = token ? await api.login(token, current) : await api.startConversation();
    store.save(session);
    return session;
  }

  const once = (work: () => Promise<Session>) => (pending ??= work().finally(() => (pending = null)));

  return {
    currentToken: () => store.load()?.token,
    current: (): Session | null => store.load(),
    adopt: (session: Session) => store.save(session),
    setGetToken: (callback: GetToken | null) => (getToken = callback),
    ensure: (): Promise<Session> => {
      const saved = store.load();
      return saved ? Promise.resolve(saved) : once(() => create());
    },
    renew: () => once(() => (store.clear(), create())),
    identify: () => once(() => create(store.load()?.token)),
  };
}

export type Auth = ReturnType<typeof createAuth>;

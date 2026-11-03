import type { Api } from "./api";
import type { Auth } from "./auth";
import type { Session } from "./types";

// The server's limits (app/chat/context.py). A hint it would refuse is dropped here with a
// warning, because one bad value makes the server refuse the whole batch and the rest is lost.
const PROPERTY_KEY = /^[a-z][a-z0-9_]{0,39}$/;
const TAG = /^[a-z0-9][a-z0-9_.:-]{0,39}$/;
const MAX_VALUE_LENGTH = 100;
const MAX_ITEMS = 20;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\x00-\x1f\x7f]/;

/**
 * Public hints the shop's page gives about the visitor (`Mew('addProperty', 'device', 'iphone')`,
 * `Mew('addTag', 'landing-sale')`). They are kept here as the state the page wants and sent to the
 * conversation before a message, and straight away when a conversation already exists. A hint
 * never blocks the chat: if sending fails it is tried again with the next message.
 */
export function createContext(api: Api, auth: Auth) {
  const properties = new Map<string, string | null>(); // null = remove it
  const addTags = new Set<string>();
  const removeTags = new Set<string>();
  let version = 0;
  let synced = ""; // `${conversationId}:${version}` last sent

  const warn = (what: string) => console.warn(`Mew: ignored ${what}`);

  function command(name: string, ...args: unknown[]) {
    const [first, second] = args;
    if (name === "addProperty" || name === "removeProperty") {
      const key = String(first);
      const value = name === "addProperty" ? String(second) : null;
      if (!PROPERTY_KEY.test(key)) return warn(`property key "${key}" (lowercase letters, digits and _, starting with a letter)`);
      if (value !== null && (value.length > MAX_VALUE_LENGTH || CONTROL_CHARS.test(value))) return warn(`value of "${key}" (too long or has control characters)`);
      if (value !== null && !properties.has(key) && properties.size >= MAX_ITEMS) return warn(`property "${key}" (at most ${MAX_ITEMS})`);
      properties.set(key, value);
    } else {
      const tag = String(first);
      if (!TAG.test(tag)) return warn(`tag "${tag}" (lowercase letters, digits and _ . : -)`);
      if (name === "addTag") {
        if (!addTags.has(tag) && addTags.size >= MAX_ITEMS) return warn(`tag "${tag}" (at most ${MAX_ITEMS})`);
        removeTags.delete(tag);
        addTags.add(tag);
      } else {
        addTags.delete(tag);
        removeTags.add(tag);
      }
    }
    version += 1;
    const session = auth.current(); // never starts a conversation just for a hint
    if (session) void sync(session);
  }

  async function sync(session: Session): Promise<void> {
    const mark = `${session.conversationId}:${version}`;
    if (version === 0 || mark === synced) return;
    try {
      await api.updateContext(session, {
        properties: Object.fromEntries(properties),
        add_tags: [...addTags],
        remove_tags: [...removeTags],
      });
      synced = mark;
    } catch {
      /* hints are not worth failing a message for; the next one tries again */
    }
  }

  return { command, sync };
}

export type Context = ReturnType<typeof createContext>;

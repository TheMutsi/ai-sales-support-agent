import { describe, expect, it } from "vitest";
import { CONVERSATION_WINDOW_MS, createSessionStore } from "./sessionStore";
import type { Session } from "./types";

const session = (token = "t1", expiresAt = "2999-01-01T00:00:00Z"): Session => ({
  token,
  conversationId: "c1",
  expiresAt,
  identityLevel: "anonymous",
});

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  } as Storage;
}

describe("session store", () => {
  const make = (now: () => number, storage = memoryStorage()) => createSessionStore("pk", storage, now, null);

  it("returns a saved session until the 24 hour window since the last activity passes", () => {
    let t = 1_000;
    const store = make(() => t);
    store.save(session());
    t += CONVERSATION_WINDOW_MS - 1;
    expect(store.load()?.token).toBe("t1");
    store.touch();
    t += CONVERSATION_WINDOW_MS - 1;
    expect(store.load()?.token).toBe("t1");
    t += 2;
    expect(store.load()).toBeNull();
  });

  it("ignores a session the server has expired", () => {
    const store = make(() => Date.parse("2030-01-01"));
    store.save(session("t1", "2029-01-01T00:00:00Z"));
    expect(store.load()).toBeNull();
  });

  it("survives broken storage", () => {
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => {} } as unknown as Storage;
    const store = make(Date.now, broken);
    expect(() => store.save(session())).not.toThrow();
    expect(store.load()).toBeNull();
  });
});

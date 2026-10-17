import { describe, expect, it, vi } from "vitest";
import { ApiError, type Api } from "./api";
import { createAuth } from "./auth";
import { applyEvent, initialState, type ChatState } from "./chatState";
import { createChat } from "./chat";
import { createSessionStore } from "./sessionStore";
import type { ChatEvent, Session } from "./types";

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

describe("applyEvent", () => {
  const run = (events: ChatEvent[], from: ChatState = initialState) => events.reduce(applyEvent, from);
  const done: ChatEvent = { event: "done", data: { identity_required: false, identity_methods: [] } };

  it("builds the answer from deltas and finishes the turn", () => {
    const state = run([{ event: "delta", data: { text: "Hel" } }, { event: "delta", data: { text: "lo" } }, done], { ...initialState, streaming: true });
    expect(state.messages.map((m) => m.content)).toEqual(["Hello"]);
    expect(state.streaming).toBe(false);
  });

  it("drops text said before a knowledge-base search (reset), keeping only the real answer", () => {
    const state = run([{ event: "delta", data: { text: "Let me check" } }, { event: "reset", data: {} }, { event: "delta", data: { text: "It costs $10" } }, done]);
    expect(state.messages.map((m) => m.content)).toEqual(["It costs $10"]);
  });

  it("replaces what was streamed when a guardrail corrects it", () => {
    const state = run([{ event: "delta", data: { text: "Refund issued" } }, { event: "correction", data: { text: "I cannot issue refunds" } }, done]);
    expect(state.messages.map((m) => m.content)).toEqual(["I cannot issue refunds"]);
  });

  it("offers the identity methods only when the assistant asked for them", () => {
    const asked = run([{ event: "message", data: { text: "Who are you?" } }, { event: "done", data: { identity_required: true, identity_methods: ["otp"] } }]);
    expect(asked.identityMethods).toEqual(["otp"]);
  });

  it("ends the turn with an error", () => {
    const state = run([{ event: "error", data: {} }], { ...initialState, streaming: true });
    expect(state.streaming).toBe(false);
    expect(state.error).toBeTruthy();
  });
});

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    startConversation: vi.fn(async () => session("anon")),
    login: vi.fn(async () => session("logged")),
    messages: vi.fn(async () => []),
    chat: vi.fn(async function* () {}),
    resume: vi.fn(async function* () {}),
    ...overrides,
  } as Api;
}

describe("auth", () => {
  it("reuses the saved session and shares one request between concurrent callers", async () => {
    const api = fakeApi();
    const auth = createAuth(api, createSessionStore("pk", memoryStorage(), Date.now, null));
    await Promise.all([auth.ensure(), auth.ensure()]);
    await auth.ensure();
    expect(api.startConversation).toHaveBeenCalledTimes(1);
  });

  it("logs in with the shop's token when getToken returns one, asking again for each new session", async () => {
    const api = fakeApi();
    const auth = createAuth(api, createSessionStore("pk", memoryStorage(), Date.now, null));
    const getToken = vi.fn(async () => "shop-jwt");
    auth.setGetToken(getToken);
    expect((await auth.ensure()).token).toBe("logged");
    await auth.renew();
    expect(getToken).toHaveBeenCalledTimes(2);
    expect(api.startConversation).not.toHaveBeenCalled();
  });

  it("upgrades an anonymous session by logging in with it, keeping the conversation", async () => {
    const api = fakeApi();
    const auth = createAuth(api, createSessionStore("pk", memoryStorage(), Date.now, null));
    await auth.ensure();
    auth.setGetToken(() => "shop-jwt");
    await auth.identify();
    expect(api.login).toHaveBeenCalledWith("shop-jwt", "anon");
  });
});

describe("chat", () => {
  const setup = (api: Api) => {
    const store = createSessionStore("pk", memoryStorage(), Date.now, null);
    return createChat(api, createAuth(api, store), store);
  };

  it("sends a message and shows the streamed answer", async () => {
    const api = fakeApi({
      chat: vi.fn(async function* () {
        yield { event: "delta", data: { text: "Hi" } } as ChatEvent;
        yield { event: "done", data: { identity_required: false, identity_methods: [] } } as ChatEvent;
      }),
    });
    const chat = setup(api);
    await chat.send("hello");
    expect(chat.getState().messages.map((m) => [m.role, m.content])).toEqual([["user", "hello"], ["assistant", "Hi"]]);
    expect(chat.getState().streaming).toBe(false);
  });

  it("gets a new session and retries once when the server rejects it", async () => {
    let calls = 0;
    const api = fakeApi({
      chat: vi.fn(async function* () {
        if (calls++ === 0) throw new ApiError(401, "invalid_session");
        yield { event: "done", data: { identity_required: false, identity_methods: [] } } as ChatEvent;
      }),
    });
    const chat = setup(api);
    await chat.send("hello");
    expect(api.chat).toHaveBeenCalledTimes(2);
    expect(api.startConversation).toHaveBeenCalledTimes(2);
    expect(chat.getState().error).toBeNull();
  });

  it("tells the visitor when the previous message is still being answered", async () => {
    const api = fakeApi({ chat: vi.fn(async function* () { throw new ApiError(409, "turn_in_progress"); }) });
    const chat = setup(api);
    await chat.send("hello");
    expect(chat.getState().error).toMatch(/still answering/i);
    expect(chat.getState().streaming).toBe(false);
  });

  it("ignores empty messages and sends while a turn is running", async () => {
    const api = fakeApi();
    const chat = setup(api);
    await chat.send("   ");
    expect(api.chat).not.toHaveBeenCalled();
  });
});

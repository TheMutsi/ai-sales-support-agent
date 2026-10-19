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
    expect(asked.identity).toEqual({ methods: ["otp"] });
    expect(asked.messages.at(-1)?.kind).toBe("identity_request");
  });

  it("starts waiting for a person after a turn that opened a ticket, or when told so", () => {
    const escalated = run([{ event: "message", data: { text: "A ticket was opened." } }, { event: "done", data: { identity_required: false, identity_methods: [], ticket_created: true } }]);
    expect(escalated.handoff).toBe("waiting");
    const told = run([{ event: "done", data: { identity_required: false, identity_methods: [], handoff: "active" } }]);
    expect(told.handoff).toBe("active");
    expect(told.messages).toEqual([]); // the message was stored; there is no answer to show
    expect(run([done]).handoff).toBe("none");
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
    messages: vi.fn(async () => ({ messages: [], handoff: "none" as const })),
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

  it("offers the identity form again after a reload when the last stored message asked for it", async () => {
    const stored = (kind: "text" | "identity_request") => [{ id: "seq-2", role: "assistant" as const, kind, content: "Please verify" }];
    const pending = setup(fakeApi({ messages: vi.fn(async () => ({ messages: stored("identity_request"), handoff: "none" as const })) }));
    await pending.load();
    expect(pending.getState().identity).toEqual({ methods: ["otp", "order_id"] });
    const answered = setup(fakeApi({ messages: vi.fn(async () => ({ messages: stored("text"), handoff: "none" as const })) }));
    await answered.load();
    expect(answered.getState().identity).toBeNull();
  });
});


describe("while a person has the conversation", () => {
  /** A chat that already has a saved session, as one has once the panel was opened. */
  function chatWithSession(api: Api) {
    const store = createSessionStore("pk", memoryStorage(), Date.now, null);
    store.save(session());
    return createChat(api, createAuth(api, store), { touch() {} } as never);
  }

  const person = [
    { id: "seq-1", role: "user" as const, kind: "text" as const, content: "I want a person" },
    { id: "seq-2", role: "system" as const, kind: "system" as const, content: "Mónica joined the chat." },
    { id: "seq-3", role: "human" as const, kind: "text" as const, content: "Hi, I am Mónica.", author: "Mónica" },
  ];

  it("shows what the person wrote and when they are done", async () => {
    const messages = vi.fn()
      .mockResolvedValueOnce({ messages: person, handoff: "active" })
      .mockResolvedValueOnce({ messages: person, handoff: "none" });
    const chat = chatWithSession(fakeApi({ messages }));
    await chat.refresh();
    expect(chat.getState().handoff).toBe("active");
    expect(chat.getState().messages.at(-1)).toMatchObject({ role: "human", author: "Mónica" });
    await chat.refresh();
    expect(chat.getState().handoff).toBe("none");
  });

  it("keeps the previews of the images the visitor attached", async () => {
    const chat = chatWithSession(fakeApi({ messages: vi.fn(async () => ({ messages: person, handoff: "active" as const })) }));
    const images = [{ url: "blob:x", alt: "receipt" }];
    await chat.send("I want a person", images);
    await chat.refresh();
    expect(chat.getState().messages[0].images).toEqual(images);
  });

  it("never renews or starts a session from a poll, whatever the server says", async () => {
    const api = fakeApi({ messages: vi.fn(async () => { throw new ApiError(401, "session_expired"); }) });
    const store = createSessionStore("pk", memoryStorage(), Date.now, null);
    const auth = createAuth(api, store);
    const chat = createChat(api, auth, { touch() {} } as never);

    await chat.refresh(); // no saved session: nothing to ask about
    expect(api.messages).not.toHaveBeenCalled();

    store.save(session());
    await chat.refresh(); // a rejected session
    expect(api.messages).toHaveBeenCalledTimes(1);
    expect(api.startConversation).not.toHaveBeenCalled();
    expect(api.login).not.toHaveBeenCalled();
    expect(chat.getState().error).toBe("Your session expired. Send a message to continue.");
  });

  it("lets only the newest poll change the screen", async () => {
    let release: (value: { messages: never[]; handoff: "none" }) => void = () => {};
    const slow = new Promise<{ messages: never[]; handoff: "none" }>((resolve) => (release = resolve));
    const messages = vi.fn()
      .mockReturnValueOnce(slow)
      .mockResolvedValueOnce({ messages: person, handoff: "active" });
    const api = fakeApi({ messages });
    const store = createSessionStore("pk", memoryStorage(), Date.now, null);
    store.save(session());
    const chat = createChat(api, createAuth(api, store), { touch() {} } as never);

    const first = chat.refresh();
    await chat.refresh();
    release({ messages: [], handoff: "none" }); // the older answer arrives last
    await first;

    expect(chat.getState().handoff).toBe("active");
  });

  it("does not turn a failed poll into an error on screen", async () => {
    const chat = chatWithSession(fakeApi({ messages: vi.fn(async () => { throw new Error("offline"); }) }));
    await chat.refresh();
    expect(chat.getState().error).toBeNull();
  });
});

describe("cards of a turn", () => {
  it("attach to the answer that the done event closes", async () => {
    const { applyEvent, initialState } = await import("./chatState");
    const card = { type: "action" as const, id: "a", title: "Yes", message: "Yes, cancel it" };
    let state = applyEvent(initialState, { event: "delta", data: { text: "Sure?" } });
    state = applyEvent(state, { event: "done", data: { identity_required: false, identity_methods: [], cards: [card] } });

    expect(state.messages.at(-1)).toMatchObject({ role: "assistant", content: "Sure?", cards: [card] });
  });
});


describe("a button click", () => {
  const card = { type: "action" as const, id: "offer-refund", title: "$14.00 back", message: "I'll take the $14.00 refund", action: "take_refund", order_id: null };

  function chatWithSession(api: Api) {
    const store = createSessionStore("pk", memoryStorage(), Date.now, null);
    store.save(session());
    return createChat(api, createAuth(api, store), store);
  }

  it("is sent as the action, not as text, and says in the conversation what its card says", async () => {
    const api = fakeApi();
    const chat = chatWithSession(api);

    await chat.pick(card);

    expect(api.chat).toHaveBeenCalledWith(expect.anything(), { type: "action", action: "take_refund", order_id: null }, expect.any(String));
    expect(chat.getState().messages[0]).toMatchObject({ role: "user", content: "I'll take the $14.00 refund" });
  });

  it("is sent as written when the card was stored before actions existed", async () => {
    const api = fakeApi();
    const chat = chatWithSession(api);

    await chat.pick({ ...card, action: undefined });

    expect(api.chat).toHaveBeenCalledWith(expect.anything(), { type: "text", message: "I'll take the $14.00 refund" }, expect.any(String));
  });

  it("ends the conversation when the server rejects it as malformed, and restart begins a new one", async () => {
    const api = fakeApi({ chat: vi.fn(() => { throw new ApiError(422, "validation_error"); }) as never });
    const chat = chatWithSession(api);

    await chat.pick(card);
    expect(chat.getState()).toMatchObject({ broken: true, streaming: false, error: null });

    chat.restart();
    expect(chat.getState()).toMatchObject({ broken: false, messages: [] });
  });
});

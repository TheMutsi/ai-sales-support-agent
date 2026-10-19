import { describe, expect, it, vi } from "vitest";
import { ApiError, createApi } from "./api";

const sessionJson = {
  session_token: "tok",
  conversation_id: "c1",
  expires_at: "2999-01-01T00:00:00Z",
  identity_level: "order_lookup",
};

describe("orderLookup", () => {
  it("posts the key, email and order id, carrying the current session so the conversation continues", async () => {
    const fetchFn = vi.fn(async () => new Response(JSON.stringify(sessionJson), { status: 200 }));
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);

    const session = await api.orderLookup("ana@example.com", "A1b2C3d4E5f6G7h8I9j0", "anon-token");

    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/auth/order-lookup");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      api_key: "pk_x",
      email: "ana@example.com",
      order_id: "A1b2C3d4E5f6G7h8I9j0",
    });
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer anon-token");
    expect(session).toEqual({ token: "tok", conversationId: "c1", expiresAt: sessionJson.expires_at, identityLevel: "order_lookup" });
  });

  it("turns the generic 401 into an ApiError carrying its code", async () => {
    const fetchFn = vi.fn(
      async () => new Response(JSON.stringify({ detail: { code: "invalid_order_lookup" } }), { status: 401 }),
    );
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);

    await expect(api.orderLookup("a@b.co", "A1b2C3d4E5f6G7h8I9j0")).rejects.toMatchObject({
      status: 401,
      code: "invalid_order_lookup",
    });
    expect(new ApiError(401, "x")).toBeInstanceOf(Error);
  });
});

describe("requestOtp", () => {
  it("carries the current session so the audit record is tied to its conversation, and sends no code", async () => {
    const fetchFn = vi.fn(async () => new Response(null, { status: 202 }));
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);

    await api.requestOtp("ana@example.com", "anon-token");

    const [url, init] = fetchFn.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/api/auth/otp/request");
    expect(JSON.parse(init.body as string)).toEqual({ api_key: "pk_x", email: "ana@example.com" });
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer anon-token");
  });
});

describe("cards", () => {
  const product = { type: "product", id: "o1", name: "Pro plan", price: "$69.99", image: { url: "/api/assets/products/pro.svg", alt: "Pro plan" } };
  const action = { type: "action", id: "a", title: "Yes", message: "Yes, cancel it" };

  it("makes a picture on the API absolute when the stored messages are read", async () => {
    const fetchFn = vi.fn(async () =>
      new Response(JSON.stringify({ messages: [{ seq: 2, role: "assistant", kind: "text", content: "Offer", cards: [product, action] }], handoff: "none" })),
    );
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);

    const { messages } = await api.messages({ token: "t", conversationId: "c1", expiresAt: "", identityLevel: "store_login" });

    expect(messages[0].cards).toEqual([
      { ...product, image: { url: "http://api.test/api/assets/products/pro.svg", alt: "Pro plan" } },
      action,
    ]);
  });

  it("does the same for the cards of the done event of a turn", async () => {
    const body = `event: message\ndata: {"text":"Offer"}\n\nevent: done\ndata: ${JSON.stringify({ identity_required: false, identity_methods: [], cards: [product] })}\n\n`;
    const fetchFn = vi.fn(async () => new Response(body));
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);
    const session = { token: "t", conversationId: "c1", expiresAt: "", identityLevel: "store_login" };

    const events = [];
    for await (const event of api.chat(session, { type: "text", message: "hi" }, "m1")) events.push(event);

    const done = events.at(-1)!;
    expect(done.event === "done" && done.data.cards?.[0]).toMatchObject({ image: { url: "http://api.test/api/assets/products/pro.svg" } });
  });
});


describe("picture addresses", () => {
  it("accepts only http(s) ones and drops anything else", async () => {
    const card = (url: string) => ({ type: "product", id: url, name: "x", image: { url, alt: "x" } });
    const fetchFn = vi.fn(async () =>
      new Response(JSON.stringify({ messages: [{ seq: 1, role: "assistant", kind: "text", content: "", cards: [card("javascript:alert(1)"), card("data:image/svg+xml,x"), card("https://cdn.test/a.png")] }] })),
    );
    const api = createApi("http://api.test", "pk_x", fetchFn as unknown as typeof fetch);

    const { messages } = await api.messages({ token: "t", conversationId: "c1", expiresAt: "", identityLevel: "store_login" });

    expect(messages[0].cards?.map((c) => (c.type === "product" ? c.image.url : null))).toEqual(["", "", "https://cdn.test/a.png"]);
  });
});

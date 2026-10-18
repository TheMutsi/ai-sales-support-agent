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

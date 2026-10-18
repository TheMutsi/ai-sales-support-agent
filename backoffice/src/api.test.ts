import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, login, updateConfig } from "./api";

function reply(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => body });
}

afterEach(() => vi.unstubAllGlobals());

describe("the admin API client", () => {
  it("sends the session as a bearer token", async () => {
    const fetchMock = reply(200, {});
    vi.stubGlobal("fetch", fetchMock);
    await updateConfig("tok", "t1", { allowed_origins: ["https://a.example"] });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/tenants/t1/config");
    expect(init.method).toBe("PATCH");
    expect(init.headers.Authorization).toBe("Bearer tok");
  });

  it("turns the backend's error code into an ApiError", async () => {
    vi.stubGlobal("fetch", reply(403, { detail: { code: "forbidden" } }));
    await expect(login("viewer", "t1")).rejects.toMatchObject({ status: 403, code: "forbidden" });
  });

  it("keeps what a validation problem says", async () => {
    vi.stubGlobal("fetch", reply(422, { detail: [{ msg: "Value error, not a plain origin" }] }));
    const error = await login("admin", "t1").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe("Value error, not a plain origin");
  });
});

import { describe, expect, it, vi } from "vitest";
import type { Api } from "./api";
import type { Auth } from "./auth";
import type { Chat } from "./chat";
import { createIdentity } from "./identity";
import type { Session } from "./types";

const upgraded: Session = { token: "verified", conversationId: "c1", expiresAt: "2999-01-01T00:00:00Z", identityLevel: "email_verified" };

describe("identity with a one-time code", () => {
  it("verifies with the current session, adopts the new one, then answers the waiting message", async () => {
    const order: string[] = [];
    const api = { verifyOtp: vi.fn(async () => (order.push("verify"), upgraded)) } as unknown as Api;
    const auth = { currentToken: () => "anon", adopt: vi.fn(() => void order.push("adopt")) } as unknown as Auth;
    const chat = { resume: vi.fn(async () => void order.push("resume")) } as unknown as Chat;
    await createIdentity(api, auth, chat).verify("ana@example.com", "123456");
    expect(api.verifyOtp).toHaveBeenCalledWith("ana@example.com", "123456", "anon");
    expect(auth.adopt).toHaveBeenCalledWith(upgraded);
    expect(order).toEqual(["verify", "adopt", "resume"]);
  });

  it("does not resume (or change the session) when the code is wrong", async () => {
    const api = { verifyOtp: vi.fn(async () => { throw new Error("401"); }) } as unknown as Api;
    const auth = { currentToken: () => "anon", adopt: vi.fn() } as unknown as Auth;
    const chat = { resume: vi.fn() } as unknown as Chat;
    await expect(createIdentity(api, auth, chat).verify("ana@example.com", "000000")).rejects.toThrow();
    expect(auth.adopt).not.toHaveBeenCalled();
    expect(chat.resume).not.toHaveBeenCalled();
  });
});

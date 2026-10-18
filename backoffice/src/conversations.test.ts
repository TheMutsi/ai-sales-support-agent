import { describe, expect, it } from "vitest";
import type { ConversationSummary } from "./api";
import { identificationLine, nextCursor, who } from "./conversations";

const item = (minute: number): ConversationSummary => ({
  id: String(minute),
  identity_level: "anonymous",
  customer: null,
  created_at: "2026-01-01T00:00:00",
  last_activity_at: `2026-01-01T00:${String(minute).padStart(2, "0")}:00`,
  message_count: 2,
  first_message: "hi",
});

describe("how a conversation reads", () => {
  it("names a visitor without a customer as anonymous and never shows a full email", () => {
    expect(who({ customer: null })).toBe("Anonymous visitor");
    expect(who({ customer: { name: "Ana", email_masked: "a***@s***.test" } })).toBe("Ana (a***@s***.test)");
  });

  it("describes an identification attempt, with the reason of a failure", () => {
    const event = { method: "otp", outcome: "failed", reason: "wrong_code", email_masked: null, created_at: "" };
    expect(identificationLine(event)).toBe("one-time code: failed (wrong_code)");
    expect(identificationLine({ ...event, method: "store_login", outcome: "succeeded", reason: null })).toBe(
      "the shop's login: succeeded",
    );
  });

  it("offers an older page only when the last one was full, from the last item's activity", () => {
    const full = Array.from({ length: 50 }, (_, i) => item(i));
    expect(nextCursor(full)).toBe(full[49].last_activity_at);
    expect(nextCursor(full.slice(0, 7))).toBeUndefined();
    expect(nextCursor([])).toBeUndefined();
  });
});

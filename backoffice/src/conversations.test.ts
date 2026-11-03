import { describe, expect, it } from "vitest";
import type { ConversationSummary } from "./api";
import { identificationLine, metadataRows, nextCursor, who } from "./conversations";

const item = (minute: number): ConversationSummary => ({
  id: String(minute),
  identity_level: "anonymous",
  customer: null,
  created_at: "2026-01-01T00:00:00",
  last_activity_at: `2026-01-01T00:${String(minute).padStart(2, "0")}:00`,
  message_count: 2,
  first_message: "hi",
  tags: [],
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

describe("metadata", () => {
  it("lists the identity with how it was linked, and the handoff with the agent", () => {
    const detail = {
      id: "c1", identity_level: "store_login", linked_via: "store_login", handoff_status: "active",
      handoff_agent_name: "Sam", properties: {}, tags: [], customer: null,
      created_at: "2026-01-01T00:00:00", last_activity_at: "2026-01-01T00:01:00", messages: [], identification: [],
    };
    const rows = Object.fromEntries(metadataRows(detail));
    expect(rows["Identity"]).toBe("store_login (via store_login)");
    expect(rows["Handoff"]).toBe("active (Sam)");
    const plain = Object.fromEntries(metadataRows({ ...detail, linked_via: null, handoff_agent_name: null }));
    expect(plain["Identity"]).toBe("store_login");
    expect(plain["Handoff"]).toBe("active");
  });
});

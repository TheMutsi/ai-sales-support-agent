import { describe, expect, it } from "vitest";
import type { EscalationItem } from "./api";
import { speaker, waitingLine } from "./escalations";

const item = (over: Partial<EscalationItem>): EscalationItem => ({
  id: "1",
  handoff_status: "waiting",
  agent_name: null,
  requested_at: "2026-01-01T12:00:00Z",
  customer: null,
  ticket: null,
  last_message: null,
  ...over,
});
const at = (iso: string) => new Date(iso);

describe("how the inbox reads", () => {
  it("says how long someone has waited", () => {
    expect(waitingLine(item({}), at("2026-01-01T12:12:30Z"))).toBe("Waiting 12 min");
    expect(waitingLine(item({}), at("2026-01-01T12:00:20Z"))).toBe("Waiting, just now");
  });

  it("never shows a negative wait when the clocks differ", () => {
    expect(waitingLine(item({}), at("2026-01-01T11:59:00Z"))).toBe("Waiting, just now");
  });

  it("says who has a conversation an agent is in", () => {
    expect(waitingLine(item({ handoff_status: "active", agent_name: "Mónica" }))).toBe("With Mónica");
  });

  it("names the speakers from the person's side", () => {
    expect(speaker({ role: "human", author_name: "Mónica" })).toBe("Mónica");
    expect(speaker({ role: "user", author_name: null })).toBe("Visitor");
    expect(speaker({ role: "assistant", author_name: null })).toBe("assistant");
  });
});

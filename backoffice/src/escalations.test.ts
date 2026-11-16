import { describe, expect, it } from "vitest";
import type { EscalationItem } from "./api";
import { escalationQuery } from "./api";
import { reasonLine, speaker, splitList, waitingLine } from "./escalations";

const item = (over: Partial<EscalationItem>): EscalationItem => ({
  id: "1",
  reference: "MF-ABCD2345",
  route: "live",
  reason: "agent_available",
  category: "escalation",
  status: "open",
  handoff_status: "waiting",
  agent_name: null,
  escalated_at: "2026-01-01T12:00:00Z",
  resolved_at: null,
  resolved_by: null,
  notes: null,
  customer: null,
  tags: [],
  properties: {},
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

  it("reads an offline follow-up and a resolved one", () => {
    const offline = item({ route: "offline", handoff_status: "none" });
    expect(waitingLine(offline, at("2026-01-01T12:20:00Z"))).toBe("Follow-up pending, 20 min");
    expect(waitingLine(offline, at("2026-01-01T12:00:10Z"))).toBe("Follow-up pending, just now");
    expect(waitingLine(item({ status: "resolved", resolved_by: "Mónica" }))).toBe("Resolved by Mónica");
  });

  it("explains why a visitor got a number instead of a person", () => {
    expect(reasonLine("outside_support_hours")).toBe("Outside support hours");
    expect(reasonLine(null)).toBe("");
  });

  it("builds the search the server understands", () => {
    const query = new URLSearchParams(
      escalationQuery({ status: "all", route: "offline", q: "  parcel ", tags: ["vip", "sale"], properties: ["device:iphone"] }),
    );
    expect(query.get("status")).toBe("all");
    expect(query.get("route")).toBe("offline");
    expect(query.get("q")).toBe("parcel");
    expect(query.getAll("tag")).toEqual(["vip", "sale"]);
    expect(query.getAll("property")).toEqual(["device:iphone"]);
    expect(escalationQuery({ status: "open", q: "  " })).toBe("status=open");
  });

  it("splits the typed tags and drops the blanks", () => {
    expect(splitList(" vip, ,sale ")).toEqual(["vip", "sale"]);
    expect(splitList("")).toEqual([]);
  });

  it("names the speakers from the person's side", () => {
    expect(speaker({ role: "human", author_name: "Mónica" })).toBe("Mónica");
    expect(speaker({ role: "user", author_name: null })).toBe("Visitor");
    expect(speaker({ role: "assistant", author_name: null })).toBe("assistant");
  });
});

import { describe, expect, it } from "vitest";
import { buildOverrides, messageFor, parseOrigins, toggleScope } from "./config";

describe("the configuration form", () => {
  it("reads one origin per line and ignores blanks", () => {
    expect(parseOrigins(" https://a.example \n\n https://b.example\n")).toEqual([
      "https://a.example",
      "https://b.example",
    ]);
  });

  it("clears the overrides when no level is customised", () => {
    expect(buildOverrides({})).toBeNull();
    expect(buildOverrides({ order_lookup: ["kb:read"] })).toEqual({ order_lookup: ["kb:read"] });
  });

  it("drops a level the backend does not know", () => {
    expect(buildOverrides({ nobody: ["kb:read"] })).toBeNull();
  });

  it("toggles a scope on and off without touching the others", () => {
    expect(toggleScope(["kb:read"], "order:read")).toEqual(["kb:read", "order:read"]);
    expect(toggleScope(["kb:read", "order:read"], "kb:read")).toEqual(["order:read"]);
  });

  it("explains known codes and passes validation messages through", () => {
    expect(messageFor(403, "forbidden")).toMatch(/role/);
    expect(messageFor(422, "not a plain origin")).toBe("not a plain origin");
    expect(messageFor(500, "request_failed")).toBe("The change was refused.");
  });
});

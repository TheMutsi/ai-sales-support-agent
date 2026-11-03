import { describe, expect, it, vi } from "vitest";
import type { Api } from "./api";
import type { Auth } from "./auth";
import { createContext } from "./context";
import type { Session } from "./types";

const session: Session = { token: "t", conversationId: "c1", expiresAt: "2999-01-01", identityLevel: "anonymous" };

function setup(current: Session | null = session) {
  const updateContext = vi.fn().mockResolvedValue(undefined);
  const context = createContext({ updateContext } as unknown as Api, { current: () => current } as unknown as Auth);
  return { context, updateContext };
}

describe("page hints", () => {
  it("sends the hints at once when a conversation exists", async () => {
    const { context, updateContext } = setup();
    context.command("addProperty", "device", "iphone");
    context.command("addTag", "landing-sale");
    await vi.waitFor(() => expect(updateContext).toHaveBeenCalledTimes(2));
    expect(updateContext).toHaveBeenLastCalledWith(session, {
      properties: { device: "iphone" },
      add_tags: ["landing-sale"],
      remove_tags: [],
    });
  });

  it("holds them without a conversation and sends them before the first message", async () => {
    const { context, updateContext } = setup(null);
    context.command("addProperty", "device", "iphone");
    expect(updateContext).not.toHaveBeenCalled();
    await context.sync(session);
    expect(updateContext).toHaveBeenCalledOnce();
  });

  it("does not send the same state twice to a conversation", async () => {
    const { context, updateContext } = setup(null);
    context.command("addTag", "a");
    await context.sync(session);
    await context.sync(session);
    expect(updateContext).toHaveBeenCalledOnce();
  });

  it("removes a property with null and a tag with remove_tags", async () => {
    const { context, updateContext } = setup(null);
    context.command("removeProperty", "device");
    context.command("removeTag", "old");
    await context.sync(session);
    expect(updateContext).toHaveBeenCalledWith(session, { properties: { device: null }, add_tags: [], remove_tags: ["old"] });
  });

  it("drops what the server would refuse, so the rest still goes", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { context, updateContext } = setup(null);
    context.command("addProperty", "Bad Key", "x");
    context.command("addProperty", "ok", "x".repeat(101));
    context.command("addTag", "Has Space");
    context.command("addProperty", "plan", "club");
    await context.sync(session);
    expect(updateContext).toHaveBeenCalledWith(session, { properties: { plan: "club" }, add_tags: [], remove_tags: [] });
    expect(warn).toHaveBeenCalledTimes(3);
  });

  it("keeps going when sending fails, and tries again with the next message", async () => {
    const { context, updateContext } = setup(null);
    updateContext.mockRejectedValueOnce(new Error("offline"));
    context.command("addTag", "a");
    await context.sync(session);
    await context.sync(session);
    expect(updateContext).toHaveBeenCalledTimes(2);
  });
});

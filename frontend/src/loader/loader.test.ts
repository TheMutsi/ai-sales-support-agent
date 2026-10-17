import { describe, expect, it, vi } from "vitest";
import { createController } from "./controller";
import { installGlobal, readKey } from "./global";

describe("controller", () => {
  it("opens, closes, hides and shows", () => {
    const c = createController();
    c.run("open");
    expect(c.getState()).toEqual({ open: true, visible: true });
    c.run("close");
    expect(c.getState().open).toBe(false);
    c.run("open");
    c.run("hide");
    expect(c.getState()).toEqual({ open: false, visible: false });
    c.run("show");
    expect(c.getState().visible).toBe(true);
  });

  it("ignores unknown commands without throwing", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const c = createController();
    c.run("explode");
    expect(c.getState()).toEqual({ open: false, visible: true });
    expect(warn).toHaveBeenCalled();
  });

  it("notifies subscribers and stops after unsubscribe", () => {
    const c = createController();
    const listener = vi.fn();
    const off = c.subscribe(listener);
    c.run("open");
    off();
    c.run("close");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("installGlobal", () => {
  it("replays calls queued before the script loaded, in order", () => {
    const c = createController();
    const win = {} as unknown as Window;
    const stub = function () {
      (stub.q = stub.q ?? []).push(arguments);
    } as { (...a: unknown[]): void; q?: IArguments[] };
    (win as unknown as { Mew: typeof stub }).Mew = stub;
    stub("open");
    stub("hide");
    installGlobal(win, c);
    expect(c.getState()).toEqual({ open: false, visible: false });
    (win as unknown as { Mew: (cmd: string) => void }).Mew("show");
    expect(c.getState().visible).toBe(true);
  });
});

describe("Mew('config', ...)", () => {
  it("hands the options to the config handler instead of running a command", () => {
    const c = createController();
    const win = { Mew: undefined } as unknown as Window;
    const onConfig = vi.fn();
    installGlobal(win, c, onConfig);
    const getToken = () => "jwt";
    (win as unknown as { Mew: (...a: unknown[]) => void }).Mew("config", { getToken });
    expect(onConfig).toHaveBeenCalledWith({ getToken });
    expect(c.getState()).toEqual({ open: false, visible: true });
  });
});

describe("readKey", () => {
  it("reads the key from the script URL", () => {
    const s = document.createElement("script");
    s.src = "https://cdn.example.com/mew.js?key=pk_test";
    expect(readKey(s)).toBe("pk_test");
  });

  it("returns null without a key or script", () => {
    const s = document.createElement("script");
    s.src = "https://cdn.example.com/mew.js";
    expect(readKey(s)).toBeNull();
    expect(readKey(null)).toBeNull();
  });
});

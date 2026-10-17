import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";
import { IdentityForm } from "./IdentityForm";
import { MessageView } from "./MessageView";
import { toParts } from "./parts";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("toParts", () => {
  it("turns urls into links and keeps the text around them", () => {
    expect(toParts("Pay here: https://shop.example/checkout?id=1. Thanks!")).toEqual([
      { type: "text", text: "Pay here: " },
      { type: "link", url: "https://shop.example/checkout?id=1", label: "https://shop.example/checkout?id=1" },
      { type: "text", text: ". Thanks!" },
    ]);
  });

  it("never makes a link out of a non-http scheme", () => {
    expect(toParts("click javascript:alert(1) or data:text/html,x")).toEqual([
      { type: "text", text: "click javascript:alert(1) or data:text/html,x" },
    ]);
  });
});

let root: Root | null = null;
const container = document.createElement("div");
document.body.appendChild(container);
const mount = (node: React.ReactNode) => {
  root = createRoot(container);
  act(() => root!.render(node));
};
afterEach(() => act(() => root?.unmount()));

describe("MessageView", () => {
  it("renders a message as text, not HTML, with safe links", () => {
    mount(<MessageView message={{ id: "1", role: "assistant", kind: "text", content: "<b>hi</b> https://a.example/x" }} />);
    expect(container.querySelector("b")).toBeNull();
    const link = container.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://a.example/x");
    expect(link.rel).toBe("noopener noreferrer");
  });
});

describe("Composer", () => {
  const type = (textarea: HTMLTextAreaElement, value: string) =>
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
  const press = (textarea: HTMLTextAreaElement, init: KeyboardEventInit) =>
    act(() => void textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, ...init })));

  it("sends on Enter, adds a line on Shift+Enter, and clears the field", () => {
    const onSend = vi.fn();
    mount(<Composer disabled={false} onSend={onSend} />);
    const textarea = container.querySelector("textarea")!;
    type(textarea, " hello ");
    press(textarea, { shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    press(textarea, {});
    expect(onSend).toHaveBeenCalledExactlyOnceWith("hello");
    expect(textarea.value).toBe("");
  });

  it("does not send while a turn is running or when empty", () => {
    const onSend = vi.fn();
    mount(<Composer disabled onSend={onSend} />);
    const textarea = container.querySelector("textarea")!;
    type(textarea, "hello");
    press(textarea, {});
    expect(onSend).not.toHaveBeenCalled();
    expect(container.querySelector("button")!.disabled).toBe(true);
  });
});

describe("IdentityForm", () => {
  const set = (input: HTMLInputElement, value: string) =>
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  const submit = async () => {
    await act(async () => void container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  };

  it("asks for the email, then the code, and verifies both", async () => {
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => {}) };
    mount(<IdentityForm identity={identity} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    expect(identity.requestCode).toHaveBeenCalledWith("ana@example.com");
    set(container.querySelector("input")!, "12a3456");
    await submit();
    expect(identity.verify).toHaveBeenCalledWith("ana@example.com", "123456");
  });

  it("rejects a malformed email or short code without calling the server", async () => {
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => {}) };
    mount(<IdentityForm identity={identity} />);
    set(container.querySelector("input")!, "not-an-email");
    await submit();
    expect(identity.requestCode).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });

  it("says only that the code did not work when verification fails", async () => {
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => { throw new Error("401"); }) };
    mount(<IdentityForm identity={identity} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    set(container.querySelector("input")!, "123456");
    await submit();
    expect(container.querySelector('[role="alert"]')!.textContent).toBe("That code did not work.");
  });
});

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";
import { IdentityForm } from "./IdentityForm";
import { MessageView } from "./MessageView";
import { toParts } from "./parts";
import { rejection } from "./attachments";
import { answeredCount, nextUnread } from "./unread";

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

describe("a person in the conversation", () => {
  it("shows their message under their name and a notice as a notice", () => {
    mount(
      <>
        <MessageView message={{ id: "1", role: "human", kind: "text", content: "Hi, I am <b>Mónica</b>", author: "Mónica" }} />
        <MessageView message={{ id: "2", role: "system", kind: "system", content: "Mónica joined the chat." }} />
      </>,
    );
    expect(container.querySelector(".mew-human .mew-author")?.textContent).toBe("Mónica");
    expect(container.querySelector("b")).toBeNull(); // text, not HTML
    expect(container.querySelector(".mew-notice")?.textContent).toBe("Mónica joined the chat.");
  });

  it("counts a person's message as new, and a notice as nothing", () => {
    const base = { kind: "text" as const, content: "x" };
    expect(
      answeredCount([
        { id: "1", role: "assistant", ...base },
        { id: "2", role: "human", ...base },
        { id: "3", role: "system", kind: "system", content: "joined" },
        { id: "4", role: "user", ...base },
      ]),
    ).toBe(2);
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
    expect(onSend).toHaveBeenCalledExactlyOnceWith("hello", []);
    expect(textarea.value).toBe("");
  });

  it("does not send while a turn is running or when empty", () => {
    const onSend = vi.fn();
    mount(<Composer disabled onSend={onSend} />);
    const textarea = container.querySelector("textarea")!;
    type(textarea, "hello");
    press(textarea, {});
    expect(onSend).not.toHaveBeenCalled();
    expect(container.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled).toBe(true);
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
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => {}), verifyOrder: vi.fn(async () => {}) };
    mount(<IdentityForm identity={identity} methods={["otp"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    expect(identity.requestCode).toHaveBeenCalledWith("ana@example.com");
    set(container.querySelector("input")!, "12a3456");
    await submit();
    expect(identity.verify).toHaveBeenCalledWith("ana@example.com", "123456");
  });

  it("rejects a malformed email or short code without calling the server", async () => {
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => {}), verifyOrder: vi.fn(async () => {}) };
    mount(<IdentityForm identity={identity} methods={["otp"]} />);
    set(container.querySelector("input")!, "not-an-email");
    await submit();
    expect(identity.requestCode).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });

  it("says only that the code did not work when verification fails", async () => {
    const identity = { requestCode: vi.fn(async () => {}), verify: vi.fn(async () => { throw new Error("401"); }), verifyOrder: vi.fn(async () => {}) };
    mount(<IdentityForm identity={identity} methods={["otp"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    set(container.querySelector("input")!, "123456");
    await submit();
    expect(container.querySelector('[role="alert"]')!.textContent).toBe("That code did not work.");
  });
});

describe("unread count", () => {
  it("counts answers that arrive while closed, ignoring history and the one still streaming", () => {
    let state = nextUnread({ seen: null, unread: 0 }, 4, false); // old conversation: baseline only
    expect(state.unread).toBe(0);
    state = nextUnread(state, 5, false);
    expect(state.unread).toBe(1);
    state = nextUnread(state, 6, false);
    expect(state.unread).toBe(2);
    state = nextUnread(state, 6, true); // opening the panel clears it
    expect(state).toEqual({ seen: 6, unread: 0 });
    expect(answeredCount([
      { id: "u", role: "user", kind: "text", content: "hi" },
      { id: "streaming", role: "assistant", kind: "text", content: "Hel" },
      { id: "answer-2", role: "assistant", kind: "text", content: "Hello" },
    ])).toBe(1);
  });
});

describe("attachment rules", () => {
  const file = (type: string, size = 10) => new File([new Uint8Array(size)], "a", { type });

  it("accepts small images and rejects other types, big files and more than three", () => {
    expect(rejection(file("image/png"), 0)).toBeNull();
    expect(rejection(file("application/pdf"), 0)).toMatch(/only png/i);
    expect(rejection(file("image/svg+xml"), 0)).not.toBeNull(); // svg can carry script
    expect(rejection(file("image/png", 5 * 1024 * 1024 + 1), 0)).toMatch(/5 MB/);
    expect(rejection(file("image/png"), 3)).toMatch(/up to 3/i);
  });
});

describe("Composer attachments", () => {
  it("previews a chosen image, can remove it, and sends it with the message", async () => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    const onSend = vi.fn();
    mount(<Composer disabled={false} onSend={onSend} />);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const choose = (files: File[]) =>
      act(() => {
        Object.defineProperty(input, "files", { value: files, configurable: true });
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    choose([new File(["x"], "cat.png", { type: "image/png" })]);
    expect(container.querySelector("img")!.getAttribute("src")).toBe("blob:preview");
    expect(container.textContent).toMatch(/not sent yet/i);
    act(() => container.querySelector<HTMLButtonElement>('[aria-label="Remove cat.png"]')!.click());
    expect(container.querySelector("img")).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");

    choose([new File(["x"], "cat.png", { type: "image/png" })]);
    const textarea = container.querySelector("textarea")!;
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, "look");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => void textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(onSend).toHaveBeenCalledWith("look", [{ url: "blob:preview", name: "cat.png" }]);
  });

  it("explains why a file was refused", () => {
    mount(<Composer disabled={false} onSend={vi.fn()} />);
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    act(() => {
      Object.defineProperty(input, "files", { value: [new File(["x"], "a.pdf", { type: "application/pdf" })], configurable: true });
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(container.querySelector('[role="alert"]')!.textContent).toMatch(/only png/i);
  });
});

describe("IdentityForm with an order number", () => {
  const ORDER = "A1b2C3d4E5f6G7h8I9j0";
  const stub = (overrides = {}) => ({
    requestCode: vi.fn(async () => {}),
    verify: vi.fn(async () => {}),
    verifyOrder: vi.fn(async () => {}),
    ...overrides,
  });
  const set = (input: HTMLInputElement, value: string) =>
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  const submit = async () => {
    await act(async () => void container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  };
  const click = async (label: RegExp) => {
    const button = [...container.querySelectorAll("button")].find((b) => label.test(b.textContent ?? ""))!;
    await act(async () => void button.click());
  };

  it("asks for the email first and then lets the visitor choose how to prove it", async () => {
    const identity = stub();
    mount(<IdentityForm identity={identity} methods={["otp", "order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();

    expect(identity.requestCode).not.toHaveBeenCalled(); // nothing is sent until they choose
    expect(container.textContent).toMatch(/email me a code/i);
    expect(container.textContent).toMatch(/order number/i);

    await click(/order number/i);
    set(container.querySelector("input")!, ORDER);
    await submit();
    expect(identity.verifyOrder).toHaveBeenCalledWith("ana@example.com", ORDER);
    expect(identity.requestCode).not.toHaveBeenCalled();
  });

  it("sends the code when the visitor chooses the code", async () => {
    const identity = stub();
    mount(<IdentityForm identity={identity} methods={["otp", "order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    await click(/email me a code/i);

    expect(identity.requestCode).toHaveBeenCalledWith("ana@example.com");
    expect(container.textContent).toMatch(/code we emailed/i);
  });

  it("goes straight to the order number when it is the only method (a customer who has no order in the session)", async () => {
    const identity = stub();
    mount(<IdentityForm identity={identity} methods={["order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();

    expect(container.textContent).toMatch(/order number/i);
    expect(identity.requestCode).not.toHaveBeenCalled();
  });

  it("rejects an order number of the wrong shape without calling the server", async () => {
    const identity = stub();
    mount(<IdentityForm identity={identity} methods={["order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    // The field keeps only letters and digits, so what is left of these is too short.
    for (const bad of ["short", "A1b2C3d4E5f6G7h8I9j-", "é".repeat(20), ""]) {
      set(container.querySelector("input")!, bad);
      await submit();
      expect(identity.verifyOrder).not.toHaveBeenCalled();
      expect(container.querySelector('[role="alert"]')).not.toBeNull();
    }
  });

  it("keeps only the first 20 letters and digits of what is typed or pasted", () => {
    mount(<IdentityForm identity={stub()} methods={["order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    act(() => void container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    set(container.querySelector("input")!, `  ${ORDER}-extra `);

    expect(container.querySelector("input")!.value).toBe(ORDER);
  });

  it("says only that the email and order did not match, whatever went wrong", async () => {
    const identity = stub({ verifyOrder: vi.fn(async () => { throw new Error("401"); }) });
    mount(<IdentityForm identity={identity} methods={["order_id"]} />);
    set(container.querySelector("input")!, "ana@example.com");
    await submit();
    set(container.querySelector("input")!, ORDER);
    await submit();

    expect(container.querySelector('[role="alert"]')!.textContent).toBe(
      "We couldn't match that email and order number.",
    );
  });
});


describe("the menu", () => {
  it("only lets 'Help & Support' lead anywhere; the other entries are drawn and do nothing", async () => {
    const { Menu } = await import("./Menu");
    const onHelp = vi.fn();
    mount(<Menu onHelp={onHelp} onClose={() => {}} />);
    const items = Array.from(container.querySelectorAll<HTMLButtonElement>(".mew-menu-item"));

    expect(items.map((item) => item.textContent)).toEqual([
      "Manage Order",
      "Track my Order",
      "Exchanges & Returns",
      "Manage Memberships",
      "Manage my TV Show Order",
      "Help & Support",
    ]);
    items.slice(0, -1).forEach((item) => {
      expect(item.getAttribute("aria-disabled")).toBe("true");
      act(() => item.click());
    });
    expect(onHelp).not.toHaveBeenCalled();

    act(() => items.at(-1)!.click());
    expect(onHelp).toHaveBeenCalledTimes(1);
  });
});

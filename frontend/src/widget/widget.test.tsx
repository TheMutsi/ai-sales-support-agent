import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";
import { IdentityForm } from "./IdentityForm";
import { MessageView } from "./MessageView";
import { toParts } from "./parts";
import { rejection } from "./attachments";
import { answeredCount, nextUnread } from "./unread";
import type { ChatState } from "../data/chatState";

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

describe("the panel's views", () => {
  const fakeChat = (state: Partial<ChatState> = {}) => {
    let current: ChatState = { messages: [], streaming: false, error: null, identity: null, handoff: "none", ...state };
    const listeners = new Set<() => void>();
    return {
      load: vi.fn(async () => {}),
      refresh: vi.fn(async () => {}),
      send: vi.fn(async () => {}),
      getState: () => current,
      subscribe: (fn: () => void) => (listeners.add(fn), () => listeners.delete(fn)),
      set: (next: Partial<ChatState>) => {
        current = { ...current, ...next };
        listeners.forEach((fn) => fn());
      },
    };
  };
  const mountApp = async (chat: ReturnType<typeof fakeChat>) => {
    const { App } = await import("./App");
    const { createController } = await import("../loader/controller");
    const controller = createController();
    controller.run("open");
    mount(<App controller={controller} chat={chat as never} identity={{} as never} settings={{ sound: false }} />);
    return controller;
  };
  const click = (text: string) =>
    act(() => Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes(text))!.click());

  it("starts on the menu, loads nothing there, and loads the conversation when Help & Support is chosen", async () => {
    const chat = fakeChat();
    await mountApp(chat);

    expect(container.querySelector(".mew-menu")).not.toBeNull();
    expect(chat.load).not.toHaveBeenCalled();
    expect(chat.refresh).toHaveBeenCalled(); // only looks, it never starts a conversation

    click("Help & Support");
    expect(container.querySelector(".mew-menu")).toBeNull();
    expect(chat.load).toHaveBeenCalledTimes(1);

    click("Back to menu");
    expect(container.querySelector(".mew-menu")).not.toBeNull();
  });

  it("goes straight to the chat when a person already has the conversation", async () => {
    await mountApp(fakeChat({ handoff: "active" }));
    expect(container.querySelector(".mew-menu")).toBeNull();
    expect(container.querySelector(".mew-composer")).not.toBeNull();
  });

  it("takes a visitor on the menu to the chat when a person turns out to be in it", async () => {
    const chat = fakeChat();
    await mountApp(chat);
    act(() => chat.set({ handoff: "waiting" }));
    expect(container.querySelector(".mew-menu")).toBeNull();
  });

  it("does not call a stored conversation unread when the menu looks it up", async () => {
    const chat = fakeChat();
    chat.refresh.mockImplementation(async () => {
      chat.set({ messages: [{ id: "1", role: "assistant", kind: "text", content: "hi" }, { id: "2", role: "assistant", kind: "text", content: "again" }] });
    });
    await mountApp(chat);
    await act(async () => {});

    expect(container.querySelector(".mew-menu-badge")).toBeNull();
    expect(container.querySelector(".mew-badge")).toBeNull();
  });

  it("counts an answer that arrives while the menu is showing as unread, on the Help entry", async () => {
    const chat = fakeChat({ messages: [{ id: "1", role: "assistant", kind: "text", content: "hi" }] });
    await mountApp(chat); // what was already there is the baseline, not unread
    act(() => chat.set({ messages: [{ id: "1", role: "assistant", kind: "text", content: "hi" }, { id: "2", role: "human", kind: "text", content: "hello" }] }));

    expect(container.querySelector(".mew-menu-badge")?.textContent).toBe("1");
  });
});

describe("cards", () => {
  const action = { type: "action" as const, id: "offer-points", title: "2,100 points", badge: "30% in points", message: "I'll take the 2,100 points" };
  const product = {
    type: "product" as const, id: "o1", name: "Pro plan", price: "$69.99", badge: "Open",
    image: { url: "http://api.test/api/assets/products/pro.svg", alt: "Pro plan" },
  };

  it("sends an action card's message when it is chosen, only while it is the latest reply", async () => {
    const { Cards } = await import("./Cards");
    const onPick = vi.fn();
    mount(<Cards cards={[action]} active onPick={onPick} onZoom={() => {}} />);
    act(() => container.querySelector<HTMLButtonElement>(".mew-action")!.click());
    expect(onPick).toHaveBeenCalledWith("I'll take the 2,100 points");

    act(() => root!.unmount());
    onPick.mockClear();
    mount(<Cards cards={[action]} active={false} onPick={onPick} onZoom={() => {}} />);
    expect(container.querySelector<HTMLButtonElement>(".mew-action")!.disabled).toBe(true);
  });

  it("shows a product small and opens its picture large, closing with Escape", async () => {
    const { Cards, Lightbox } = await import("./Cards");
    const onZoom = vi.fn();
    mount(<Cards cards={[product]} active onPick={() => {}} onZoom={onZoom} />);
    expect(container.querySelector(".mew-product strong")?.textContent).toBe("Pro plan");
    expect(container.querySelector(".mew-price")?.textContent).toBe("$69.99");
    act(() => container.querySelector<HTMLButtonElement>(".mew-product-image")!.click());
    expect(onZoom).toHaveBeenCalledWith([product.image]);

    act(() => root!.unmount());
    const onClose = vi.fn();
    mount(<Lightbox images={[product.image]} onClose={onClose} />);
    expect(container.querySelector(".mew-lightbox img")?.getAttribute("src")).toBe(product.image.url);
    act(() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })));
    expect(onClose).toHaveBeenCalled();
  });

  it("draws the cards of an assistant message under its text", () => {
    const cardsProps = { active: true, onPick: () => {}, onZoom: () => {} };
    mount(<MessageView message={{ id: "1", role: "assistant", kind: "text", content: "Pick one", cards: [action] }} cards={cardsProps} />);
    expect(container.querySelector(".mew-assistant")?.textContent).toBe("Pick one");
    expect(container.querySelectorAll(".mew-card")).toHaveLength(1);
  });

  it("only lets the latest reply's cards be used, and not while busy or when a person has the chat", async () => {
    const { MessageList } = await import("./MessageList");
    const messages = [
      { id: "1", role: "assistant" as const, kind: "text" as const, content: "old", cards: [action] },
      { id: "2", role: "assistant" as const, kind: "text" as const, content: "new", cards: [action] },
    ];
    const state = (busy: boolean, locked: boolean) => {
      act(() => root?.unmount());
      mount(<MessageList messages={messages} waiting={false} busy={busy} locked={locked} onPick={() => {}} onZoom={() => {}} />);
      return Array.from(container.querySelectorAll<HTMLButtonElement>(".mew-action")).map((b) => b.disabled);
    };

    expect(state(false, false)).toEqual([true, false]);
    expect(state(true, false)).toEqual([true, true]);
    expect(state(false, true)).toEqual([true, true]);
  });

  it("gives the focus back to the picture when the large one is closed", async () => {
    const { Cards, Lightbox } = await import("./Cards");
    const Host = () => {
      const [images, setImages] = React.useState<(typeof product.image)[] | null>(null);
      return (
        <>
          <Cards cards={[product]} active onPick={() => {}} onZoom={setImages} />
          {images && <Lightbox images={images} onClose={() => setImages(null)} />}
        </>
      );
    };
    mount(<Host />);
    const thumb = container.querySelector<HTMLButtonElement>(".mew-product-image")!;
    act(() => thumb.focus());
    act(() => thumb.click());
    expect(document.activeElement).toBe(container.querySelector(".mew-lightbox-close"));
    act(() => container.querySelector<HTMLButtonElement>(".mew-lightbox-close")!.click());
    expect(document.activeElement).toBe(thumb);
  });

  it("draws a divider between a gift and the choices that come with it", async () => {
    const { Cards } = await import("./Cards");
    mount(<Cards cards={[product, { type: "divider", id: "d", label: "+" }, action]} active onPick={() => {}} onZoom={() => {}} />);
    const order = Array.from(container.querySelector(".mew-cards")!.children).map((el) => el.className.split(" ").pop());
    expect(order).toEqual(["mew-product", "mew-divider", "mew-action"]);
    expect(container.querySelector(".mew-divider b")?.textContent).toBe("+");
  });

  it("stacks a second picture behind the first, shows a struck price, and lets the large view switch pictures", async () => {
    const { Cards, Lightbox } = await import("./Cards");
    const gift = {
      type: "product" as const, id: "g", name: "Shapermint Essentials Everyday Wireless Jelly Bra", price: "GIFT", compare_price: "$49.99",
      image: { url: "https://cdn.test/gift.jpg", alt: "Shapermint Essentials Everyday Wireless Jelly Bra" },
    };
    const leggings = {
      ...product, more_images: [{ url: "https://cdn.test/back.jpg", alt: "Pro plan" }],
    };
    const onZoom = vi.fn();
    mount(<Cards cards={[gift, leggings]} active onPick={() => {}} onZoom={onZoom} />);

    expect(container.querySelector(".mew-compare")?.textContent).toBe("$49.99");
    expect(container.querySelector(".mew-compare")?.tagName).toBe("S");
    const [first, second] = Array.from(container.querySelectorAll(".mew-product-image"));
    expect(first.querySelectorAll("img")).toHaveLength(1);
    expect(second.querySelector(".mew-stack-back")?.getAttribute("src")).toBe("https://cdn.test/back.jpg");
    act(() => (second as HTMLButtonElement).click());
    expect(onZoom).toHaveBeenCalledWith([leggings.image, leggings.more_images[0]]);

    act(() => root!.unmount());
    mount(<Lightbox images={[leggings.image, leggings.more_images[0]]} onClose={() => {}} />);
    expect(container.querySelector(".mew-lightbox > img")?.getAttribute("src")).toBe(leggings.image.url);
    act(() => container.querySelectorAll<HTMLButtonElement>(".mew-lightbox-thumbs button")[1].click());
    expect(container.querySelector(".mew-lightbox > img")?.getAttribute("src")).toBe("https://cdn.test/back.jpg");
  });
});

describe("scrolling", () => {
  const withCards = { id: "2", role: "assistant" as const, kind: "text" as const, content: "Choose", cards: [{ type: "action" as const, id: "a", title: "x", message: "x" }] };
  const plain = { id: "1", role: "assistant" as const, kind: "text" as const, content: "Hello" };

  it("decides from the card types: cards hold the scroll, a plain answer follows it, and the set can change", async () => {
    const { scrollModeFor, HOLD_SCROLL_FOR } = await import("./scroll");

    expect(scrollModeFor(withCards)).toBe("message-start");
    expect(scrollModeFor(plain)).toBe("end");
    expect(scrollModeFor(undefined)).toBe("end");
    (HOLD_SCROLL_FOR as Set<string>).delete("action");
    expect(scrollModeFor(withCards)).toBe("end"); // taking a type out of the set brings back autoscroll
    (HOLD_SCROLL_FOR as Set<string>).add("action");
  });

  it("scrolls to the start of a reply with cards, and to the bottom for anything else", async () => {
    const { MessageList } = await import("./MessageList");
    const calls: { el: string; block: unknown }[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function (arg?: boolean | ScrollIntoViewOptions) {
      calls.push({ el: this.hasAttribute("data-message") ? "message" : "end", block: (arg as ScrollIntoViewOptions)?.block });
    };
    try {
      const props = { waiting: false, busy: false, locked: false, onPick: () => {}, onZoom: () => {} };
      mount(<MessageList messages={[plain]} {...props} />);
      expect(calls.at(-1)).toEqual({ el: "end", block: "end" });

      act(() => root!.render(<MessageList messages={[plain, withCards]} {...props} />));
      expect(calls.at(-1)).toEqual({ el: "message", block: "start" });
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});

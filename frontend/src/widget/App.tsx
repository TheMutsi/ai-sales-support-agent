import { useEffect, useSyncExternalStore } from "react";
import type { Chat } from "../data/chat";
import type { Controller } from "../loader/controller";

export function App({ controller, chat, apiKey }: { controller: Controller; chat: Chat; apiKey: string }) {
  const { open, visible } = useSyncExternalStore(controller.subscribe, controller.getState);
  const { messages } = useSyncExternalStore(chat.subscribe, chat.getState);

  // The conversation is only fetched (and an anonymous one only created) when the panel opens.
  useEffect(() => {
    if (open) void chat.load();
  }, [open, chat]);

  if (!visible) return null;
  return (
    <div className="mew-root">
      {open && (
        <section className="mew-panel" aria-label="Chat">
          <header>Mew</header>
          <p>
            Connected with key <code>{apiKey}</code>: {messages.length} stored messages. The chat UI
            arrives in the next PR.
          </p>
        </section>
      )}
      <button
        className="mew-launcher"
        aria-label={open ? "Close chat" : "Open chat"}
        onClick={() => controller.run(open ? "close" : "open")}
      >
        {open ? "×" : "💬"}
      </button>
    </div>
  );
}

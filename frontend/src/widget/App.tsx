import { useEffect, useSyncExternalStore } from "react";
import type { Chat } from "../data/chat";
import type { Controller } from "../loader/controller";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";

export function App({ controller, chat }: { controller: Controller; chat: Chat }) {
  const { open, visible } = useSyncExternalStore(controller.subscribe, controller.getState);
  const { messages, streaming, error } = useSyncExternalStore(chat.subscribe, chat.getState);

  // The conversation is only fetched (and an anonymous one only created) when the panel opens.
  useEffect(() => {
    if (open) void chat.load();
  }, [open, chat]);

  if (!visible) return null;
  // Typing dots show from the moment of sending until the first word of the answer arrives.
  const waiting = streaming && messages.at(-1)?.role === "user";
  return (
    <div className="mew-root">
      {open && (
        <section className="mew-panel" aria-label="Chat">
          <header>Mew</header>
          <MessageList messages={messages} waiting={waiting} />
          {error && <div className="mew-error" role="alert">{error}</div>}
          <Composer disabled={streaming} onSend={(text) => void chat.send(text)} />
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

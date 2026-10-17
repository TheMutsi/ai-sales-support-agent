import { useEffect, useSyncExternalStore } from "react";
import type { Chat } from "../data/chat";
import type { Identity } from "../data/identity";
import type { Controller } from "../loader/controller";
import { Composer } from "./Composer";
import { IdentityForm } from "./IdentityForm";
import { MessageList } from "./MessageList";
import { playPing } from "./sound";
import { answeredCount, useUnread } from "./unread";

export function App({
  controller,
  chat,
  identity,
  settings,
}: {
  controller: Controller;
  chat: Chat;
  identity: Identity;
  settings: { sound: boolean };
}) {
  const { open, visible } = useSyncExternalStore(controller.subscribe, controller.getState);
  const { messages, streaming, error, identity: identityRequest } = useSyncExternalStore(chat.subscribe, chat.getState);

  // The conversation is only fetched (and an anonymous one only created) when the panel opens.
  useEffect(() => {
    if (open) void chat.load();
  }, [open, chat]);

  const unread = useUnread(answeredCount(messages), open, () => settings.sound && playPing());

  if (!visible) return null;
  // Typing dots show from the moment of sending until the first word of the answer arrives.
  const waiting = streaming && messages.at(-1)?.role === "user";
  return (
    <div className="mew-root">
      {open && (
        <section className="mew-panel" aria-label="Chat">
          <header>Mew</header>
          <MessageList messages={messages} waiting={waiting} />
          {identityRequest &&
            (identityRequest.methods.includes("otp") ? (
              <IdentityForm identity={identity} />
            ) : (
              <div className="mew-error" role="status">Please log in on the shop's site to continue.</div>
            ))}
          {error && <div className="mew-error" role="alert">{error}</div>}
          <Composer disabled={streaming} onSend={(text, images) => void chat.send(text, images.map((i) => ({ url: i.url, alt: i.name })))} />
        </section>
      )}
      <button
        className="mew-launcher"
        aria-label={open ? "Close chat" : "Open chat"}
        onClick={() => controller.run(open ? "close" : "open")}
      >
        {open ? "×" : "💬"}
        {!open && unread > 0 && (
          <span className="mew-badge" role="status" aria-label={unread === 1 ? "1 unread message" : `${unread} unread messages`}>
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
    </div>
  );
}

import { useEffect, useState, useSyncExternalStore } from "react";
import type { Chat } from "../data/chat";
import type { Identity } from "../data/identity";
import type { Controller } from "../loader/controller";
import { Composer } from "./Composer";
import { Lightbox } from "./Cards";
import type { CardImage } from "../data/types";
import { IdentityForm } from "./IdentityForm";
import { ChevronDown, ChevronLeft, ChatIcon } from "./icons";
import { MessageList } from "./MessageList";
import { Logo, Menu } from "./Menu";
import { playPing } from "./sound";
import { answeredCount, useUnread } from "./unread";

const POLL_MS = 4000;

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
  const { messages, streaming, error, identity: identityRequest, handoff, broken } = useSyncExternalStore(
    chat.subscribe,
    chat.getState,
  );

  useEffect(() => {
    if (handoff === "none") return;
    const timer = setInterval(() => void chat.refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [handoff, chat]);

  const [view, setView] = useState<"menu" | "chat">(handoff === "none" ? "menu" : "chat");
  useEffect(() => {
    if (handoff !== "none") setView("chat");
  }, [handoff]);

  const [synced, setSynced] = useState(false);
  const [zoomed, setZoomed] = useState<CardImage[] | null>(null);
  const showingChat = open && view === "chat";
  useEffect(() => {
    if (!showingChat) setZoomed(null);
  }, [showingChat]);
  useEffect(() => {
    if (showingChat) void chat.load().finally(() => setSynced(true));
  }, [showingChat, chat]);

  useEffect(() => {
    if (open && view === "menu") void chat.refresh().finally(() => setSynced(true));
  }, [open, view, chat]);

  const unread = useUnread(answeredCount(messages), showingChat, () => settings.sound && playPing(), synced || messages.length > 0);

  if (!visible) return null;
  const waiting = streaming && messages.at(-1)?.role === "user";
  return (
    <div className="mew-root">
      {open && (
        <section className="mew-panel" aria-label="Chat">
          {view === "menu" ? (
            <Menu unread={unread} onHelp={() => setView("chat")} onClose={() => controller.run("close")} />
          ) : (
            <>
              <header className="mew-header mew-header-chat">
                <button type="button" className="mew-back" onClick={() => setView("menu")}>
                  <ChevronLeft /> Back to menu
                </button>
                <Logo online />
                <div className="mew-title">
                  <strong>Chat with us</strong>
                  <span>How can we help you today?</span>
                </div>
                <button type="button" className="mew-collapse" aria-label="Minimize chat" onClick={() => controller.run("close")}>
                  <ChevronDown />
                </button>
              </header>
              <MessageList
                messages={messages}
                waiting={waiting}
                busy={streaming}
                locked={handoff !== "none"}
                onPick={(card) => void chat.pick(card)}
                onZoom={setZoomed}
              />
              {identityRequest &&
                (identityRequest.methods.some((m) => m === "otp" || m === "order_id") ? (
                  <IdentityForm identity={identity} methods={identityRequest.methods} />
                ) : (
                  <div className="mew-error" role="status">Please log in on the shop's site to continue.</div>
                ))}
              {error && <div className="mew-error" role="alert">{error}</div>}
              {broken ? (
                <div className="mew-broken" role="alert">
                  <p>There was a problem with this conversation. Please start a new one.</p>
                  <button type="button" onClick={() => chat.restart()}>Start a new conversation</button>
                </div>
              ) : (
              <Composer disabled={streaming} onSend={(text, images) => void chat.send(text, images.map((i) => ({ url: i.url, alt: i.name })))} />
              )}
            </>
          )}
          {zoomed && zoomed.length > 0 && <Lightbox images={zoomed} onClose={() => setZoomed(null)} />}
        </section>
      )}
      <button
        className="mew-launcher"
        aria-label={open ? "Close chat" : "Open chat"}
        onClick={() => controller.run(open ? "close" : "open")}
      >
        {open ? <ChevronDown size={26} /> : <ChatIcon size={26} />}
        {!showingChat && unread > 0 && (
          <span className="mew-badge" role="status" aria-label={unread === 1 ? "1 unread message" : `${unread} unread messages`}>
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
    </div>
  );
}

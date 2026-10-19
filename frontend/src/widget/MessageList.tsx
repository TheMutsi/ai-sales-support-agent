import { useEffect, useRef } from "react";
import type { CardImage, ChatMessage } from "../data/types";
import { Avatar, MessageView } from "./MessageView";
import { scrollModeFor } from "./scroll";

export function MessageList({
  messages,
  waiting,
  busy,
  locked,
  onPick,
  onZoom,
}: {
  messages: ChatMessage[];
  waiting: boolean;
  busy: boolean;
  /** A person has the conversation: an offer of the assistant is no longer theirs to take. */
  locked: boolean;
  onPick: (message: string) => void;
  onZoom: (images: CardImage[]) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);

  // Follow the answer as it streams in (the last message's text changes without a new message),
  // except when it carries cards: then the view stays at the top of that reply (see `scroll.ts`).
  useEffect(() => {
    if (scrollModeFor(last) === "message-start") {
      const rows = list.current?.querySelectorAll("[data-message]");
      rows?.item(rows.length - 1)?.scrollIntoView?.({ block: "start" });
    } else {
      end.current?.scrollIntoView?.({ block: "end" });
    }
  }, [messages.length, last?.content, last?.cards?.length, waiting]);

  return (
    <div className="mew-messages" role="log" aria-live="polite" ref={list}>
      {messages.length === 0 && <p className="mew-empty">Hi! Ask me anything about the product.</p>}
      {messages.map((message) => (
        <MessageView
          key={message.id}
          message={message}
          cards={{ active: !busy && !locked && message.id === last?.id, onPick, onZoom }}
        />
      ))}
      {waiting && (
        <div className="mew-row-assistant">
          <Avatar />
          <div className="mew-message mew-assistant mew-typing" role="status" aria-label="Typing">
            <i /><i /><i />
          </div>
        </div>
      )}
      <div ref={end} />
    </div>
  );
}

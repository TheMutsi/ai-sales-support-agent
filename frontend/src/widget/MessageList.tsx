import { useEffect, useRef } from "react";
import type { CardImage, ChatMessage } from "../data/types";
import { Avatar, MessageView } from "./MessageView";

export function MessageList({
  messages,
  waiting,
  busy,
  onPick,
  onZoom,
}: {
  messages: ChatMessage[];
  waiting: boolean;
  busy: boolean;
  onPick: (message: string) => void;
  onZoom: (image: CardImage) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);

  // Follow the answer as it streams in: the last message's text changes without a new message.
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, last?.content, last?.cards?.length, waiting]);

  return (
    <div className="mew-messages" role="log" aria-live="polite">
      {messages.length === 0 && <p className="mew-empty">Hi! Ask me anything about the product.</p>}
      {messages.map((message) => (
        <MessageView
          key={message.id}
          message={message}
          cards={{ active: !busy && message.id === last?.id, onPick, onZoom }}
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

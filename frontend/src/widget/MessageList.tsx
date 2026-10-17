import { useEffect, useRef } from "react";
import type { ChatMessage } from "../data/types";
import { MessageView } from "./MessageView";

export function MessageList({ messages, waiting }: { messages: ChatMessage[]; waiting: boolean }) {
  const end = useRef<HTMLDivElement>(null);
  const last = messages.at(-1);

  // Follow the answer as it streams in: the last message's text changes without a new message.
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, last?.content, waiting]);

  return (
    <div className="mew-messages" role="log" aria-live="polite">
      {messages.length === 0 && <p className="mew-empty">Hi! Ask me anything about the product.</p>}
      {messages.map((message) => (
        <MessageView key={message.id} message={message} />
      ))}
      {waiting && <div className="mew-message mew-assistant mew-typing" aria-label="Typing">…</div>}
      <div ref={end} />
    </div>
  );
}

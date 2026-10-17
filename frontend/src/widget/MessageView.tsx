import type { ChatMessage } from "../data/types";
import { Markdown } from "./markdown";
import { toParts, type MessagePart } from "./parts";

function Part({ part }: { part: MessagePart }) {
  switch (part.type) {
    case "text":
      return <>{part.text}</>;
    case "link":
      return (
        <a href={part.url} target="_blank" rel="noopener noreferrer">
          {part.label}
        </a>
      );
    case "image":
      return <img src={part.url} alt={part.alt} loading="lazy" />;
  }
}

export function MessageView({ message }: { message: ChatMessage }) {
  // The assistant writes markdown; what a visitor types is shown as typed.
  if (message.role === "assistant") {
    return (
      <div className="mew-message mew-assistant">
        <Markdown text={message.content} />
      </div>
    );
  }
  const parts: MessagePart[] = [
    ...(message.images ?? []).map((image): MessagePart => ({ type: "image", ...image })),
    ...toParts(message.content),
  ];
  return (
    <div className="mew-message mew-user">
      {parts.map((part, index) => (
        <Part key={index} part={part} />
      ))}
    </div>
  );
}

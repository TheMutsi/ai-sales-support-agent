import type { ChatMessage } from "../data/types";
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
  return (
    <div className={`mew-message mew-${message.role}`}>
      {toParts(message.content).map((part, index) => (
        <Part key={index} part={part} />
      ))}
    </div>
  );
}

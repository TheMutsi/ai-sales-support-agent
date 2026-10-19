import type { ChatMessage } from "../data/types";
import { Markdown } from "./markdown";
import { toParts, type MessagePart } from "./parts";
import { Cards, type ActionCard } from "./Cards";
import type { CardImage } from "../data/types";

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

/** The assistant's picture next to what it says. */
export const Avatar = () => (
  <span className="mew-avatar" aria-hidden="true">
    M
  </span>
);

export interface CardControls {
  /** Whether this message is the latest, so its action cards may still be used. */
  active: boolean;
  onPick: (card: ActionCard) => void;
  onZoom: (images: CardImage[]) => void;
}

export function MessageView({ message, cards }: { message: ChatMessage; cards?: CardControls }) {
  // A notice ("Mónica joined the chat") is not anyone's speech.
  if (message.role === "system") return <div className="mew-notice">{message.content}</div>;
  if (message.role === "human") {
    return (
      <div className="mew-message mew-human">
        <span className="mew-author">{message.author ?? "Agent"}</span>
        {toParts(message.content).map((part, index) => (
          <Part key={index} part={part} />
        ))}
      </div>
    );
  }
  // The assistant writes markdown; what a visitor types is shown as typed.
  if (message.role === "assistant") {
    return (
      <div className="mew-row-assistant" data-message="">
        <Avatar />
        <div className="mew-stack">
          <div className="mew-message mew-assistant">
            <Markdown text={message.content} />
          </div>
          {cards && message.cards && message.cards.length > 0 && (
            <Cards cards={message.cards} active={cards.active} onPick={cards.onPick} onZoom={cards.onZoom} />
          )}
        </div>
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

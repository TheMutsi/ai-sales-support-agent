import type { Card, ChatMessage } from "../data/types";

export type ScrollMode =
  | "end"
  | "message-start";

export const HOLD_SCROLL_FOR: ReadonlySet<Card["type"]> = new Set(["action", "product", "divider"]);

export function scrollModeFor(message: ChatMessage | undefined): ScrollMode {
  const holds = message?.cards?.some((card) => HOLD_SCROLL_FOR.has(card.type));
  return holds ? "message-start" : "end";
}

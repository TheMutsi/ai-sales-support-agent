import type { Card, ChatMessage } from "../data/types";

/** Where the list scrolls to when the latest message changes. */
export type ScrollMode =
  /** Follow the conversation to the bottom (an answer being written, a new message). */
  | "end"
  /** Stay at the top of the message, so its text is read from the start and its cards are looked at. */
  | "message-start";

/**
 * The card types whose arrival holds the scroll at the top of the reply instead of jumping to
 * the bottom: a deployment of cards (offers, products) is not explicit, so the visitor must read
 * it from the beginning. Add or remove a type here to change what holds the scroll; an empty set
 * brings back autoscroll for everything.
 */
export const HOLD_SCROLL_FOR: ReadonlySet<Card["type"]> = new Set(["action", "product", "divider"]);

export function scrollModeFor(message: ChatMessage | undefined): ScrollMode {
  const holds = message?.cards?.some((card) => HOLD_SCROLL_FOR.has(card.type));
  return holds ? "message-start" : "end";
}

// How the inbox reads: plain functions, tested without a browser.

import type { EscalationItem } from "./api";

export function waitingLine(item: EscalationItem, now: Date = new Date()): string {
  if (item.handoff_status === "active") return `With ${item.agent_name ?? "an agent"}`;
  if (!item.requested_at) return "Waiting";
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(item.requested_at).getTime()) / 60000));
  return minutes < 1 ? "Waiting, just now" : `Waiting ${minutes} min`;
}

/** The name a message is shown under in the person's view of the chat. */
export const speaker = (message: { role: string; author_name: string | null }): string =>
  message.role === "human" ? (message.author_name ?? "Agent") : message.role === "user" ? "Visitor" : message.role;

// How the inbox reads: plain functions, tested without a browser.

import type { EscalationItem } from "./api";

export function waitingLine(item: EscalationItem, now: Date = new Date()): string {
  if (item.status === "resolved") return item.resolved_by ? `Resolved by ${item.resolved_by}` : "Resolved";
  if (item.handoff_status === "active") return `With ${item.agent_name ?? "an agent"}`;
  if (!item.escalated_at) return item.route === "live" ? "Waiting" : "Waiting for a follow-up";
  const minutes = Math.max(0, Math.floor((now.getTime() - new Date(item.escalated_at).getTime()) / 60000));
  if (item.route === "live") return minutes < 1 ? "Waiting, just now" : `Waiting ${minutes} min`;
  return `Follow-up pending, ${minutes < 1 ? "just now" : `${minutes} min`}`;
}

/** Why the visitor got a number instead of a person, in the agent's words. */
export const reasonLine = (reason: string | null): string =>
  ({
    not_urgent: "Not urgent (the order is on its way)",
    outside_support_hours: "Outside support hours",
    no_agent_available: "No agent was available",
    agent_available: "An agent was available",
  })[reason ?? ""] ?? "";

/** The inbox's filter as typed: tags are comma-separated, properties are `key:value` pairs. */
export const splitList = (text: string): string[] =>
  text.split(",").map((part) => part.trim()).filter(Boolean);

/** The name a message is shown under in the person's view of the chat. */
export const speaker = (message: { role: string; author_name: string | null }): string =>
  message.role === "human" ? (message.author_name ?? "Agent") : message.role === "user" ? "Visitor" : message.role;

// How a conversation reads in the list and the detail: plain functions, tested without a browser.

import type { ConversationDetail, ConversationSummary } from "./api";

export const who = (conversation: Pick<ConversationSummary, "customer">): string =>
  conversation.customer
    ? `${conversation.customer.name} (${conversation.customer.email_masked})`
    : "Anonymous visitor";

const METHODS: Record<string, string> = {
  otp: "one-time code",
  order_id: "email and order number",
  store_login: "the shop's login",
};
const OUTCOMES: Record<string, string> = { code_sent: "code sent", succeeded: "succeeded", failed: "failed" };

export function identificationLine(event: ConversationDetail["identification"][number]): string {
  const base = `${METHODS[event.method] ?? event.method}: ${OUTCOMES[event.outcome] ?? event.outcome}`;
  return event.reason ? `${base} (${event.reason})` : base;
}

/** The page after the one shown: its cursor is the last item's activity, as the API expects. */
export const nextCursor = (shown: ConversationSummary[], pageSize = 50): string | undefined =>
  shown.length > 0 && shown.length % pageSize === 0 ? shown[shown.length - 1].last_activity_at : undefined;

/** The facts of a conversation shown under "View metadata", as label/value rows. */
export function metadataRows(c: ConversationDetail): [string, string][] {
  return [
    ["Conversation id", c.id],
    ["Created", new Date(c.created_at).toLocaleString()],
    ["Last activity", new Date(c.last_activity_at).toLocaleString()],
    ["Identity", c.linked_via ? `${c.identity_level} (via ${c.linked_via})` : c.identity_level],
    ["Handoff", c.handoff_agent_name ? `${c.handoff_status} (${c.handoff_agent_name})` : c.handoff_status],
  ];
}

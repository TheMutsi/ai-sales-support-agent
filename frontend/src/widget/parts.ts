/**
 * What a message is made of. The backend sends plain text today; a message is rendered as a list
 * of typed parts so images, then cards and carousels, are one more case in `MessageView` and not a
 * rewrite. Nothing here is ever inserted as HTML.
 */
export type MessagePart =
  | { type: "text"; text: string }
  | { type: "link"; url: string; label: string }
  | { type: "image"; url: string; alt: string };

// Only http(s): a `javascript:` URL in a message must never become a clickable link.
const URL_PATTERN = /https?:\/\/[^\s<>"')]+/g;
const TRAILING_PUNCTUATION = /[.,;:!?]+$/;

export function toParts(content: string): MessagePart[] {
  const parts: MessagePart[] = [];
  let last = 0;
  for (const match of content.matchAll(URL_PATTERN)) {
    const url = match[0].replace(TRAILING_PUNCTUATION, "");
    if (match.index > last) parts.push({ type: "text", text: content.slice(last, match.index) });
    parts.push({ type: "link", url, label: url });
    last = match.index + url.length;
  }
  if (last < content.length) parts.push({ type: "text", text: content.slice(last) });
  return parts;
}

import type { ChatEvent } from "./types";

function parseBlock(block: string): ChatEvent | null {
  let event = "";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!event) return null;
  return { event, data: data.length ? JSON.parse(data.join("\n")) : {} } as ChatEvent;
}

/**
 * Turns a streamed response body into events. `EventSource` cannot be used: it only does GET
 * and cannot send the `Authorization` header, and a chat turn is a POST. A network chunk can end
 * anywhere, so text is buffered until a blank line closes an event.
 */
export async function* parseSse(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const event = parseBlock(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      if (event) yield event;
    }
  }
}

import { describe, expect, it } from "vitest";
import { parseSse } from "./sse";

const bodyOf = (...chunks: string[]) =>
  new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk));
      controller.close();
    },
  });

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of iterable) out.push(item);
  return out;
}

describe("parseSse", () => {
  it("parses events even when a chunk ends in the middle of one", async () => {
    const events = await collect(
      parseSse(bodyOf('event: delta\ndata: {"te', 'xt": "Hi"}\n\nevent: done\n', 'data: {"identity_required": false, "identity_methods": []}\n\n')),
    );
    expect(events).toEqual([
      { event: "delta", data: { text: "Hi" } },
      { event: "done", data: { identity_required: false, identity_methods: [] } },
    ]);
  });
});

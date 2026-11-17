import { describe, expect, it } from "vitest";
import { parseMarkdownBlocks } from "./markdownBlocks";

describe("the markdown preview blocks", () => {
  it("reads headings, paragraphs and lists", () => {
    const blocks = parseMarkdownBlocks("# Plans\nintro\nmore\n\n- a\n- b\n1. one\n2. two");
    expect(blocks).toEqual([
      { kind: "heading", level: 1, text: "Plans" },
      { kind: "paragraph", text: "intro\nmore" },
      { kind: "list", ordered: false, items: ["a", "b"] },
      { kind: "list", ordered: true, items: ["one", "two"] },
    ]);
  });

  it("keeps html as plain text so it can never run", () => {
    expect(parseMarkdownBlocks("<script>alert(1)</script>")).toEqual([
      { kind: "paragraph", text: "<script>alert(1)</script>" },
    ]);
  });

  it("returns nothing for an empty text", () => {
    expect(parseMarkdownBlocks("")).toEqual([]);
  });
});

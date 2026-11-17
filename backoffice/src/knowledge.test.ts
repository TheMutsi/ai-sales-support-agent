import { describe, expect, it } from "vitest";
import type { KbDocumentDetail, KbVersion } from "./api";
import {
  canSaveNewDocument,
  detailsChanged,
  detailsPayload,
  draftOf,
  editorContent,
  estimateTokens,
  fitLabel,
  kbMessageFor,
  planOptions,
  tokenLine,
} from "./knowledge";

const version = (id: string, status: string, content: string): KbVersion => ({
  id,
  version: 1,
  status,
  content,
  created_at: "2026-01-01T00:00:00Z",
  published_at: null,
  published_by: null,
  estimated_tokens: 0,
  fits_whole_document: true,
});

const document = (versions: KbVersion[], publishedId: string | null): KbDocumentDetail => ({
  id: "d",
  title: "t",
  doc_type: "faq",
  plan_scope: null,
  product_area: null,
  when_to_use: "w",
  published_version_id: publishedId,
  published_version: null,
  has_draft: versions.some((v) => v.status === "draft"),
  estimated_tokens: 0,
  fits_whole_document: true,
  versions,
});

describe("the knowledge base helpers", () => {
  it("estimates tokens as a third of the characters, rounded up", () => {
    expect(estimateTokens("")).toBe(0);
    expect(estimateTokens("abc")).toBe(1);
    expect(estimateTokens("abcd")).toBe(2);
  });

  it("says whether a document fits whole at the 3000 token limit", () => {
    expect(fitLabel(3000)).toBe("fits whole");
    expect(fitLabel(3001)).toBe("search only");
    expect(tokenLine("abcd")).toBe("~2 tokens, fits whole");
    expect(tokenLine("a".repeat(9001))).toBe("~3001 tokens, search only");
  });

  it("edits the draft first, then the published version, then the newest", () => {
    const draft = version("1", "draft", "draft text");
    const published = version("2", "published", "published text");
    const archived = version("3", "archived", "old text");
    expect(editorContent(document([draft, published], "2"))).toBe("draft text");
    expect(editorContent(document([archived, published], "2"))).toBe("published text");
    expect(editorContent(document([archived], null))).toBe("old text");
    expect(editorContent(document([], null))).toBe("");
    expect(draftOf(document([published], "2"))).toBeUndefined();
  });

  it("needs a title and a when to use before saving a new document", () => {
    expect(canSaveNewDocument({ title: "A", when_to_use: "b" })).toBe(true);
    expect(canSaveNewDocument({ title: " ", when_to_use: "b" })).toBe(false);
    expect(canSaveNewDocument({ title: "A", when_to_use: "" })).toBe(false);
  });

  it("explains the knowledge base error codes", () => {
    expect(kbMessageFor("embedding_failed")).toMatch(/embeddings/);
    expect(kbMessageFor("version_not_archived")).toMatch(/archived/);
    expect(kbMessageFor("unknown")).toBeUndefined();
  });
});

describe("kb details", () => {
  const fields = { title: " t ", doc_type: "faq", plan_scope: " ", when_to_use: " when " };

  it("trims the fields and turns a blank plan scope into null", () => {
    expect(detailsPayload(fields)).toEqual({ title: "t", doc_type: "faq", plan_scope: null, when_to_use: "when" });
  });

  it("sees a change in any of the four fields", () => {
    const loaded = { ...document([], null), when_to_use: "when" };
    expect(detailsChanged(loaded, fields)).toBe(false);
    expect(detailsChanged(loaded, { ...fields, title: "other" })).toBe(true);
    expect(detailsChanged(loaded, { ...fields, doc_type: "billing" })).toBe(true);
    expect(detailsChanged(loaded, { ...fields, plan_scope: "pro" })).toBe(true);
    expect(detailsChanged(loaded, { ...fields, when_to_use: "else" })).toBe(true);
  });
});

describe("planOptions", () => {
  const plans = [
    { slug: "starter", name: "Starter" },
    { slug: "pro", name: "Pro" },
  ];

  it("offers all visitors first, then one option per plan with the slug as value", () => {
    expect(planOptions(plans)).toEqual([
      { value: "", label: "All visitors" },
      { value: "starter", label: "Starter" },
      { value: "pro", label: "Pro" },
    ]);
  });

  it("keeps a current scope that is no longer a plan so the select still shows it", () => {
    expect(planOptions(plans, "legacy").at(-1)).toEqual({ value: "legacy", label: "legacy" });
    expect(planOptions(plans, "pro")).toHaveLength(3);
    expect(planOptions(plans, null)).toHaveLength(3);
  });

  it("has a readable message for an unknown plan", () => {
    expect(kbMessageFor("unknown_plan")).toMatch(/plan does not exist/);
  });
});

import type { KbDocumentDetail, KbDocumentDetails, KbVersion } from "./api";

export const WHOLE_DOCUMENT_TOKEN_LIMIT = 3000;

export const ALL_VISITORS_LABEL = "All visitors";

export interface PlanChoice {
  slug: string;
  name: string;
}

export interface PlanSelectOption {
  value: string;
  label: string;
}

export const planOptions = (plans: PlanChoice[], current: string | null = null): PlanSelectOption[] => {
  const options = [
    { value: "", label: ALL_VISITORS_LABEL },
    ...plans.map((plan) => ({ value: plan.slug, label: plan.name })),
  ];
  const unlisted = current !== null && current !== "" && !plans.some((plan) => plan.slug === current);
  return unlisted ? [...options, { value: current, label: current }] : options;
};

export const DOC_TYPES = ["features", "billing", "policy", "faq", "security", "integrations"] as const;

export const estimateTokens = (text: string): number => Math.ceil(text.length / 3);

export const fitsWholeDocument = (tokens: number): boolean => tokens <= WHOLE_DOCUMENT_TOKEN_LIMIT;

export const fitLabel = (tokens: number): string => (fitsWholeDocument(tokens) ? "fits whole" : "search only");

export const tokenLine = (text: string): string => {
  const tokens = estimateTokens(text);
  return `~${tokens} tokens, ${fitLabel(tokens)}`;
};

export const draftOf = (document: KbDocumentDetail): KbVersion | undefined =>
  document.versions.find((version) => version.status === "draft");

export const editorContent = (document: KbDocumentDetail): string => {
  const draft = draftOf(document);
  const published = document.versions.find((version) => version.id === document.published_version_id);
  return (draft ?? published ?? document.versions[0])?.content ?? "";
};

export const canSaveNewDocument = (fields: { title: string; when_to_use: string }): boolean =>
  fields.title.trim().length > 0 && fields.when_to_use.trim().length > 0;

export interface KbDetailFields {
  title: string;
  doc_type: string;
  plan_scope: string;
  when_to_use: string;
}

export const detailsPayload = (fields: KbDetailFields): KbDocumentDetails => ({
  title: fields.title.trim(),
  doc_type: fields.doc_type,
  plan_scope: fields.plan_scope.trim() || null,
  when_to_use: fields.when_to_use.trim(),
});

export const detailsChanged = (document: KbDocumentDetail, fields: KbDetailFields): boolean => {
  const next = detailsPayload(fields);
  return (
    next.title !== document.title ||
    next.doc_type !== document.doc_type ||
    next.plan_scope !== document.plan_scope ||
    next.when_to_use !== document.when_to_use
  );
};

const KB_MESSAGES: Record<string, string> = {
  embedding_failed: "Publishing failed because the embeddings service is unavailable. The draft is kept.",
  no_draft: "There is no draft to publish.",
  version_not_archived: "Only an archived version can be republished.",
  document_not_found: "This document no longer exists.",
  version_not_found: "This version no longer exists.",
  unknown_plan: "That plan does not exist. Pick one from the list.",
};

export const kbMessageFor = (code: string): string | undefined => KB_MESSAGES[code];

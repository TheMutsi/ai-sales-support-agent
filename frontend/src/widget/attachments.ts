export interface Attachment {
  url: string;
  name: string;
}

export const MAX_ATTACHMENTS = 3;
export const MAX_BYTES = 5 * 1024 * 1024;
const TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

export function rejection(file: File, already: number): string | null {
  if (already >= MAX_ATTACHMENTS) return `Up to ${MAX_ATTACHMENTS} images.`;
  if (!TYPES.includes(file.type)) return "Only PNG, JPEG, WebP or GIF images.";
  if (file.size > MAX_BYTES) return "Images can be up to 5 MB.";
  return null;
}

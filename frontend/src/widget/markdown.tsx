import type { ReactNode } from "react";

/**
 * The small part of markdown the assistant actually writes: paragraphs, bullet and numbered
 * lists, `**bold**`, `code`, `[label](url)` and bare urls. It builds React elements, never HTML,
 * and only http(s) urls become links, so a model answer (or a prompt injection inside it) cannot
 * add markup, scripts or `javascript:` links. Anything it does not recognise stays as plain text,
 * which is also what a half-streamed `**Star` shows until the closing marker arrives.
 */
const INLINE = /\*\*(.+?)\*\*|`([^`\n]+)`|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"')]+)/g;
const TRAILING_PUNCTUATION = /[.,;:!?]+$/;

function link(url: string, label: ReactNode, key: string) {
  return (
    <a key={key} href={url} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  );
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const key = `${keyPrefix}-${match.index}`;
    let consumed = match[0];
    if (match.index > last) nodes.push(text.slice(last, match.index));
    if (match[1] !== undefined) nodes.push(<strong key={key}>{renderInline(match[1], key)}</strong>);
    else if (match[2] !== undefined) nodes.push(<code key={key}>{match[2]}</code>);
    else if (match[3] !== undefined) nodes.push(link(match[4], renderInline(match[3], key), key));
    else {
      const url = match[5].replace(TRAILING_PUNCTUATION, "");
      consumed = url; // the punctuation after a bare url belongs to the sentence
      nodes.push(link(url, url, key));
    }
    last = match.index + consumed.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = () => {
    const key = `b${blocks.length}`;
    if (paragraph.length) {
      blocks.push(
        <p key={key}>
          {paragraph.map((line, i) => (
            <span key={i}>
              {i > 0 && <br />}
              {renderInline(line, `${key}-${i}`)}
            </span>
          ))}
        </p>,
      );
    } else if (list) {
      const items = list.items.map((item, i) => <li key={i}>{renderInline(item, `${key}-${i}`)}</li>);
      blocks.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    }
    paragraph = [];
    list = null;
  };

  for (const line of text.split("\n")) {
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const heading = HEADING.exec(line);
    if (bullet || numbered) {
      const ordered = !bullet;
      if (list && list.ordered !== ordered) flush();
      if (!list) {
        flush();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]);
    } else if (!line.trim()) {
      flush();
    } else {
      if (list) flush();
      // A heading is shown as bold text: the panel is too small for several heading sizes.
      paragraph.push(heading ? `**${heading[1]}**` : line);
    }
  }
  flush();
  return <div className="mew-md">{blocks}</div>;
}

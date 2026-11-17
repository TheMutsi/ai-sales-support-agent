import { parseMarkdownBlocks } from "./markdownBlocks";

export function MarkdownPreview({ text }: { text: string }) {
  return (
    <div className="md-preview" aria-label="Preview">
      {parseMarkdownBlocks(text).map((block, index) => {
        if (block.kind === "heading") return <h4 key={index}>{block.text}</h4>;
        if (block.kind === "list") {
          const items = block.items.map((item, i) => <li key={i}>{item}</li>);
          return block.ordered ? <ol key={index}>{items}</ol> : <ul key={index}>{items}</ul>;
        }
        return <p key={index}>{block.text}</p>;
      })}
    </div>
  );
}

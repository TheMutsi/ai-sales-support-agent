import { useRef, useState, type ChangeEvent, type KeyboardEvent } from "react";
import { rejection, type Attachment } from "./attachments";
import { SendIcon } from "./icons";

export function Composer({
  disabled,
  onSend,
}: {
  disabled: boolean;
  onSend: (text: string, images: Attachment[]) => void;
}) {
  const [text, setText] = useState("");
  const [images, setImages] = useState<Attachment[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  const submit = () => {
    if (disabled || !text.trim()) return;
    onSend(text.trim(), images);
    setText("");
    setImages([]); // the sent message keeps its preview URLs, so they are not revoked here
    setProblem(null);
  };

  const attach = (event: ChangeEvent<HTMLInputElement>) => {
    const added: Attachment[] = [];
    setProblem(null);
    for (const file of Array.from(event.target.files ?? [])) {
      const reason = rejection(file, images.length + added.length);
      if (reason) setProblem(reason);
      else added.push({ url: URL.createObjectURL(file), name: file.name });
    }
    setImages([...images, ...added]);
    event.target.value = ""; // picking the same file again must still fire a change
  };

  const remove = (url: string) => {
    URL.revokeObjectURL(url);
    setImages(images.filter((image) => image.url !== url));
  };

  // Enter sends, Shift+Enter adds a line. `isComposing` keeps an IME's Enter (choosing a
  // character) from sending a half-typed message.
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      className="mew-composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {(images.length > 0 || problem) && (
        <div className="mew-attachments">
          {images.map((image) => (
            <span key={image.url} className="mew-thumb">
              <img src={image.url} alt={image.name} />
              <button type="button" aria-label={`Remove ${image.name}`} onClick={() => remove(image.url)}>×</button>
            </span>
          ))}
          {images.length > 0 && <small>Preview only: images are not sent yet.</small>}
          {problem && <small role="alert">{problem}</small>}
        </div>
      )}
      <div className="mew-row">
        <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={attach} />
        <button type="button" className="mew-attach" aria-label="Attach an image" onClick={() => picker.current?.click()}>📎</button>
        <textarea
          value={text}
          rows={1}
          placeholder="Type a message"
          aria-label="Message"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="mew-send" aria-label="Send" disabled={disabled || !text.trim()}>
          <SendIcon />
        </button>
      </div>
    </form>
  );
}

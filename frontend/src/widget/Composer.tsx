import { useState, type KeyboardEvent } from "react";

export function Composer({ disabled, onSend }: { disabled: boolean; onSend: (text: string) => void }) {
  const [text, setText] = useState("");

  const submit = () => {
    if (disabled || !text.trim()) return;
    onSend(text.trim());
    setText("");
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
      <textarea
        value={text}
        rows={1}
        placeholder="Write a message"
        aria-label="Message"
        onChange={(event) => setText(event.target.value)}
        onKeyDown={onKeyDown}
      />
      <button type="submit" disabled={disabled || !text.trim()}>
        Send
      </button>
    </form>
  );
}

import { useSyncExternalStore } from "react";
import type { Controller } from "../loader/controller";

export function App({ controller, apiKey }: { controller: Controller; apiKey: string }) {
  const { open, visible } = useSyncExternalStore(controller.subscribe, controller.getState);

  if (!visible) return null;
  return (
    <div className="mew-root">
      {open && (
        <section className="mew-panel" aria-label="Chat">
          <header>Mew</header>
          <p>Connected with key <code>{apiKey}</code>. The conversation arrives in the next PR.</p>
        </section>
      )}
      <button
        className="mew-launcher"
        aria-label={open ? "Close chat" : "Open chat"}
        onClick={() => controller.run(open ? "close" : "open")}
      >
        {open ? "×" : "💬"}
      </button>
    </div>
  );
}

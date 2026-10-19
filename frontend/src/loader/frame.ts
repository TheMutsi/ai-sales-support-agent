/**
 * Creates the iframe the whole widget lives in. Its document is `about:blank`, so it shares the
 * shop page's origin (cookies and `fetch` behave the same) but none of its CSS or global
 * variables: a shop's `* { box-sizing: ... }` cannot restyle the chat, and ours cannot leak out.
 */
export function createFrame(host: Document): HTMLIFrameElement {
  const frame = host.createElement("iframe");
  frame.title = "Chat";
  frame.setAttribute("aria-label", "Chat");
  Object.assign(frame.style, {
    position: "fixed",
    bottom: "0",
    right: "0",
    maxWidth: "100%",
    maxHeight: "720px",
    border: "0",
    background: "transparent",
    colorScheme: "normal",
    zIndex: "2147483000",
  });
  layoutFrame(frame, { open: false, visible: true });
  host.body.appendChild(frame);
  return frame;
}

/**
 * Sizes the iframe to what is drawn inside it. `pointer-events: none` on the iframe element
 * cannot be undone from inside its document (the whole frame, content included, stops receiving
 * the mouse and focus), so the frame is shrunk to the launcher when closed instead, which keeps
 * the page behind it clickable without breaking the widget's own clicks and typing.
 */
export function layoutFrame(
  frame: HTMLIFrameElement,
  state: { open: boolean; visible: boolean },
): void {
  const { style } = frame;
  style.display = state.visible ? "block" : "none";
  style.width = state.open ? "420px" : "88px";
  style.height = state.open ? "100%" : "88px";
}

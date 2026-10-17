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
    width: "420px",
    height: "100%",
    maxWidth: "100%",
    maxHeight: "720px",
    border: "0",
    background: "transparent",
    colorScheme: "normal",
    zIndex: "2147483000",
    // Only the launcher and panel inside should catch clicks, not the empty transparent area.
    pointerEvents: "none",
  });
  host.body.appendChild(frame);
  return frame;
}

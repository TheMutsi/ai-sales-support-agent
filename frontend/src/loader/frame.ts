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

export function layoutFrame(
  frame: HTMLIFrameElement,
  state: { open: boolean; visible: boolean },
): void {
  const { style } = frame;
  style.display = state.visible ? "block" : "none";
  style.width = state.open ? "420px" : "88px";
  style.height = state.open ? "100%" : "88px";
}

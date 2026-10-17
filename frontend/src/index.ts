import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { createController } from "./loader/controller";
import { createFrame } from "./loader/frame";
import { installGlobal, readKey } from "./loader/global";
import { App } from "./widget/App";
import styles from "./widget/styles.css?inline";

// Must be read while the script is executing; afterwards `currentScript` is null.
const script = document.currentScript as HTMLScriptElement | null;

function boot() {
  const apiKey = readKey(script);
  if (!apiKey) {
    console.error("Mew: the script URL needs ?key=<your public key>");
    return;
  }
  const controller = createController();
  installGlobal(window, controller);

  const frame = createFrame(document);
  const doc = frame.contentDocument!;
  const style = doc.createElement("style");
  style.textContent = styles;
  doc.head.appendChild(style);
  doc.body.style.cssText = "margin:0;background:transparent";
  const mount = doc.createElement("div");
  doc.body.appendChild(mount);
  createRoot(mount).render(createElement(App, { controller, apiKey }));
}

// The shop may place the <script> in <head>, before <body> exists.
if (document.body) boot();
else document.addEventListener("DOMContentLoaded", boot);

import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { createApi } from "./data/api";
import { createAuth } from "./data/auth";
import { createChat } from "./data/chat";
import { createSessionStore } from "./data/sessionStore";
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
  const api = createApi(import.meta.env.VITE_API_URL ?? "http://localhost:8000", apiKey);
  const store = createSessionStore(apiKey);
  const auth = createAuth(api, store);
  const chat = createChat(api, auth, store);
  // Another tab changed the conversation (a message, a login): show the stored state.
  store.subscribe(() => void chat.load());
  installGlobal(window, controller, ({ getToken }) => {
    auth.setGetToken(getToken ?? null);
    if (getToken) void auth.identify().then(() => chat.load());
  });

  const frame = createFrame(document);
  const doc = frame.contentDocument!;
  const style = doc.createElement("style");
  style.textContent = styles;
  doc.head.appendChild(style);
  doc.body.style.cssText = "margin:0;background:transparent";
  const mount = doc.createElement("div");
  doc.body.appendChild(mount);
  createRoot(mount).render(createElement(App, { controller, chat, apiKey }));
}

// The shop may place the <script> in <head>, before <body> exists.
if (document.body) boot();
else document.addEventListener("DOMContentLoaded", boot);

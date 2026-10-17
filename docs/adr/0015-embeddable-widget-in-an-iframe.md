# ADR-0015: The widget is one script that renders into an iframe, with its state outside React

- **Status:** Accepted
- **Introduced in:** Stage 10b (PRs #89 to #95)

## Context

A shop embeds the chat on pages we do not control. Those pages have their own CSS, their own
globals, and often load their scripts in the `<head>` before the body exists. The shop must be
able to say "open the chat" or "log this customer in" at any point, including before our code
has loaded. Visitors keep one conversation across tabs and reloads for 24 hours. And what the
model writes is shown in the visitor's browser, so it must not be able to put markup there.

## Decision

- **One script, `mew.js?key=<public key>`.** Vite builds a single IIFE with no chunks and no
  separate CSS file, so the shop pastes one tag.
- **The UI lives in an `about:blank` iframe created by that script.** It has the shop page's
  origin (storage and `fetch` behave the same) but none of its CSS or globals, in either
  direction. React renders into the iframe's document.
- **A queue-style global.** The shop defines a stub that pushes onto `Mew.q`; `mew.js`
  replaces it and replays the queue in order, so `Mew('open')` works before load.
- **State outside React.** The panel state (`controller.ts`) and the conversation (`data/`) are
  plain stores that React reads with `useSyncExternalStore`, so commands and cross-tab changes
  need no mounted component.
- **The session is saved in `localStorage`**, namespaced by key, with a 24 hour window counted
  from the last activity; a `BroadcastChannel` tells other tabs to reload the conversation.
  Storage that throws is tolerated: the widget then starts a new conversation per page load.
- **The shop's server vouches for its customer** with a short-lived signed token returned by
  `getToken`, exchanged for a session. The widget asks for it again each time it needs a new
  session instead of keeping one. Everyone else is anonymous and may identify with a one-time
  code, checked by the identity endpoint and never passed through the chat
  ([ADR-0014](0014-conversation-anchored-identity-with-scopes.md)).
- **Model output has no path to HTML.** A small markdown renderer builds React elements, only
  `http(s)` urls become links, and attachments refuse SVG.
- **The streamed POST is read with `fetch`**, not `EventSource`, which cannot POST or send the
  `Authorization` header.

## Consequences

- A shop's CSS cannot break the widget and ours cannot leak out. Cost: the iframe is created
  by script, so it appears after load rather than in the first paint.
- The session token sits in the shop origin's `localStorage`, readable by the shop's own
  scripts. That is acceptable for a token scoped to one conversation, and the long-lived
  credential (the shop's signing secret) never reaches the browser.
- The bundle is about 236 kB (75 kB gzipped), mostly React. Moving to Preact is an alias change
  in Vite if size starts to matter.
- Known limits: images are previews only, an expired session retried mid-conversation opens a
  new conversation and leaves the old messages on screen, and a reload offers only the
  one-time code because the stored identity request does not record its methods.

## Alternatives

- **A cross-origin iframe served from our domain.** Stronger isolation (the shop's scripts could
  not read the session), but cookies and storage become third-party and are blocked by several
  browsers, and the widget would need its own hosting and a postMessage bridge for the shop's
  commands. Not worth it for the threat this widget faces.
- **Shadow DOM instead of an iframe.** Isolates CSS in one direction only: the shop's global
  styles still inherit in, and its scripts run in the same document.
- **A markdown library with a sanitizer.** More syntax for more dependencies and a configuration
  to get right; "there is no HTML path" is a simpler property to defend.
- **`EventSource` for streaming.** Rejected: GET only, no custom headers.

## References

- `frontend/` (README for the embed snippet and the token format)
- PRs #89 (scaffold), #90 and #91 (data layer), #92 (chat UI), #93 (identity form),
  #94 (badge, sound, attachments), #95 (markdown)

# Mew widget

The embeddable chat widget. A shop adds a script tag and gets a launcher and a chat panel
backed by this repo's API. Design reasoning: [ADR-0015](../docs/adr/0015-embeddable-widget-in-an-iframe.md).

## Embed it

```html
<script>
  window.Mew = window.Mew || function () { (Mew.q = Mew.q || []).push(arguments); };
  Mew('config', { getToken: () => fetch('/mew-token').then((r) => r.text()) }); // optional
</script>
<script async src="https://cdn.example.com/mew.js?key=pk_..."></script>
```

The first script is a stub that queues calls, so `Mew(...)` is safe to call before `mew.js` has
loaded; the real script replays the queue in order.

| Call | Effect |
|---|---|
| `Mew('open')` / `Mew('close')` | Expand or collapse the chat panel |
| `Mew('show')` / `Mew('hide')` | Show or remove the launcher (hide also closes the panel) |
| `Mew('addProperty', key, value)` / `Mew('removeProperty', key)` | Public hints about the visitor, e.g. `Mew('addProperty', 'device', 'iphone')`. Keys: lowercase letters, digits, `_`; values up to 100 characters; at most 20 |
| `Mew('addTag', tag)` / `Mew('removeTag', tag)` | Labels on the conversation, e.g. `Mew('addTag', 'landing-sale')`; at most 20 |
| `Mew('config', { getToken, sound })` | `getToken`: see below. `sound: false` turns off the new-message ping |

Without `getToken` the visitor is anonymous: they can ask knowledge-base questions, and
identify when the assistant needs to know who they are: the email always comes first, then either an
emailed one-time code or the number of one of their orders (which only lets the assistant read
that order, not the account).

## Logging in a shop's customer

The browser must never be trusted with who the customer is, so the shop's **server** vouches
for them. `getToken` returns a short-lived JWT that the shop's server signs (or `null` for a
visitor who is not logged in):

- algorithm `HS256`, signed with the secret issued to the shop (rotating: pass its id as the
  `kid` header);
- claims `sub` (the shop's own id for the customer) and `exp`, at most one hour ahead.

```js
// Node, on the shop's server, for the customer in the current session
jwt.sign({ sub: customer.id }, process.env.MEW_SECRET, {
  algorithm: 'HS256', keyid: 'dev-1', expiresIn: '10m',
});
```

The widget exchanges it for a session and never stores the token itself. `getToken` is called
again whenever a new session is needed, so the token can stay short-lived. The dev tenant's key
and secret are in `backend/app/db/seed.py` (local use only).

## How it is built

- **One IIFE script** (`vite build` in library mode): no chunks, no separate CSS, so it works
  pasted into any page. About 236 kB, 75 kB gzipped; mostly React.
- **An iframe (`about:blank`) holds the whole UI.** It keeps the same origin as the shop's page
  but none of its CSS or globals, in either direction. React renders into the iframe's document.
- **State lives outside React** (`src/loader/controller.ts`, `src/data/`), so `Mew(...)` calls
  work before, during or after the UI mounts; React subscribes with `useSyncExternalStore`.
- **No HTML path for model output.** A small markdown renderer (`src/widget/markdown.tsx`)
  builds React elements, and only `http(s)` urls become links.

```
src/index.ts          reads ?key=, creates the iframe, wires everything
src/loader/           the Mew() global and its command queue, the iframe
src/data/             API client, SSE parser, session store, auth, chat state, identity
src/widget/           React components, markdown, attachments, unread badge, sound
example/index.html    a fake shop page that embeds the widget
```

## Behaviour the code relies on

- **Product cards with two pictures** draw the second behind the first, shifted so about a
  quarter of it shows, like a stack (`.mew-stack-back`).
- **Sessions.** One session per shop, in `localStorage` (the iframe shares the page's origin), so
  every tab shares the conversation; a `BroadcastChannel` tells the others when it changes. If
  storage throws (private windows, blocked site data) the widget still works and starts a new
  conversation on each load. A conversation stays resumable for 24 hours after the last message.
  Concurrent callers share one login request, the shop's `getToken` is asked again whenever a
  new session is needed (its token is short-lived), and a rejected session is renewed once.
- **Turns.** A turn is a `fetch` POST read as server-sent events (`EventSource` cannot POST or
  send `Authorization`); text is buffered until a blank line closes an event. `delta` appends,
  `reset` drops what the model said before searching, `message` and `correction` replace. The
  turn opens only on the first event, so a rejected session fails before any text shows. A 422
  means our own widget sent something malformed: the visitor is offered a fresh start, nothing
  more. A click is sent as its action, saying what its card says; a card stored before actions
  existed is sent as text. Typing dots show from sending until the first word.
- **While a person has the conversation** the widget polls every few seconds, open or closed (the
  badge still counts). The poll never starts a conversation or renews a session, which would fork
  the visitor away from the person, never runs during a turn, and only the newest poll may change
  the screen. On the menu it still looks, without starting anything, for a conversation a person
  is in, so a reload while waiting goes straight back to it. The menu itself starts nothing.
- **Unread badge and sound.** Only finished answers count. The first look at a conversation is the
  baseline, so an old one does not light the badge; "seen" means the chat is on screen. The sound
  is a Web Audio ping, silent until the visitor has interacted with the page, and it never throws.
- **Cards and scrolling.** Action cards work only on the latest reply, not while one is being
  written, and not once a person has the conversation. A reply with cards holds the scroll at its
  top so it is read from the start (`HOLD_SCROLL_FOR` in `scroll.ts`; an empty set brings
  back autoscroll); otherwise the list follows the answer. A picture opens large and gives the
  focus back to where it was when closed.
- **Identity form.** Email first, then a code or an order number (20 ASCII letters or digits,
  what the server accepts); each step is shown whatever the server answers, and a failure gets one
  generic message, so it never reveals whether an address or an order exists.
- **Hints** (`addProperty`, `addTag`) are checked against the server's limits here, because one bad
  value makes the server refuse the whole batch. They are sent before a message, never start a
  conversation, and a failed send is retried with the next message.
- **The iframe is sized to what it draws.** `pointer-events: none` on the iframe would also stop
  the widget's own clicks, so the frame shrinks to the launcher when closed instead.
- **Markdown** covers paragraphs, lists, bold, code, links and bare urls (the punctuation after a
  bare url stays in the sentence); headings are bold text, and anything unrecognized, such as a
  half-streamed `**Star`, stays plain text. Enter sends, Shift+Enter adds a line, and an IME's
  Enter does not send. SVG is refused as an attachment because it can carry script.

## Run it

```bash
npm ci
npm test                 # vitest
npm run build            # typecheck + dist/mew.js and dist/index.html (the example shop)
npm run example          # serves dist on http://127.0.0.1:8080
```

With Docker, `docker compose up --build` serves the same on <http://localhost:8080>. The API
address is baked into the script at build time (`VITE_API_URL`, default `http://localhost:8000`)
because it runs in the visitor's browser: it must be an address the browser can reach.

Serve the example from `http://localhost:8080` or `http://127.0.0.1:8080`: those are the origins
the dev tenant allows. A page opened from `file://` has the origin `null`, which is never allowed.

## Known limits

- Image attachments are a preview only: nothing is uploaded or stored yet.
- If a session expires mid-conversation, the retry opens a new conversation and the old
  messages stay on screen.
- After a reload, the identity form offers both methods (the stored request does not record which
  it offered); the server decides what a proof is worth.
- The unread badge does not survive a page reload.

## Demo customers

The example page has one login button per demo customer (`mail1@gmail.com` to `mail4@gmail.com`, created by `python -m app.db.seed` in local environments), each with one order: open $29.99, open $69.99, in delivery $69.99, in delivery $29.99. A button signs a token in the page with the dev tenant's public secret (a real shop signs on its server), clears the widget's stored conversation and reloads, so the next customer starts clean. The dev tenant also allows `http://127.0.0.1:8081`, for a second local server.

Try, per customer: "I want to reject my order" (`mail2`: the offer of $14.00 (20%) back or $21.00 (30%) in credits, then answer it, then the last offer with a free gift; `mail1`: asked to confirm, then cancelled; `mail3`: the same offer, and declining it says to return the order once it arrives; `mail4`: told to return it once it arrives). Put the demo orders back with `python -m app.db.seed --reset-demo` (in `backend/`).

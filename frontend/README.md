# Mew widget

The embeddable chat widget. A shop adds one script tag and gets a launcher and a chat panel:

```html
<script>
  window.Mew = window.Mew || function () { (Mew.q = Mew.q || []).push(arguments); };
</script>
<script async src="https://cdn.example.com/mew.js?key=pk_..."></script>
```

`Mew('open' | 'close' | 'show' | 'hide')` can be called at any time, even before the script has
loaded: the stub above queues the calls and `mew.js` replays them in order once it is ready.

## How it is built

- **One IIFE script** (`vite build` in library mode): no chunks, no separate CSS, so it works
  pasted into any page.
- **An iframe (`about:blank`) holds the whole UI.** It keeps the same origin as the shop's page
  but none of its CSS or globals, in either direction. React renders into the iframe's document.
- **State lives outside React** (`src/loader/controller.ts`), so `Mew(...)` calls work before,
  during or after the UI mounts; React subscribes with `useSyncExternalStore`.

## Run it

```bash
npm ci
npm test                 # vitest
npm run build            # typecheck + dist/mew.js and dist/index.html (the example shop)
npm run example          # serves dist on http://127.0.0.1:8080
```

Serve the example from `http://localhost:8080` or `http://127.0.0.1:8080`: those are the origins
the dev tenant allows. A page opened from `file://` has the origin `null`, which is never allowed.

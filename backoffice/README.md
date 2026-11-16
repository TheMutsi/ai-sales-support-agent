# MewFlow back office

A separate React app (not part of the widget bundle, ADR-0016) for the people who run a shop's
assistant. Today: a placeholder login (pick a role and a tenant, no authentication) and the
tenant configuration page (allowed origins, what each identity level may do).

```bash
# backend, with the admin API switched on (it does not exist otherwise)
cd backend && ADMIN_API_ENABLED=true uvicorn app.main:app --port 8000
# back office, on http://localhost:5174 (its dev server proxies /api to :8000)
cd backoffice && npm install && npm run dev
npm test && npm run build
```

The admin API sends no CORS headers on purpose, hence the proxy. The buttons follow the
session's permissions, but the API is what enforces them.

## Behaviour the code relies on

- The session lives in `sessionStorage`: per tab and gone when it closes, since the placeholder
  login is not worth remembering longer. When storage is blocked it lasts until a reload, and the
  remembered tenant is simply forgotten.
- API errors carry the backend's `detail.code` (`session_expired`, `forbidden`...), so a page
  reacts to the code without parsing messages; a 422 already says what is wrong.
- The configuration lists mirror `app.auth.scopes`, which validates them again; a form with no
  customised level saves `null`, which clears the overrides instead of storing `{}`.
- The inbox polls every 4 seconds (the visitor's widget polls too), reloads its list only on
  "Search", not on every key, and only the newest detail request may update the screen. Every
  filter that is set must match; tags are comma-separated and properties are `key:value` pairs.
  An open escalation with nobody in the chat is offline: a person follows up later.
- The visitor's properties and tags are hints their page set, not verified facts.
- The page after the one shown is asked for with the last item's activity time as the cursor.

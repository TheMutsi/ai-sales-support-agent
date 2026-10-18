# MewFlow back office

A separate React app (not part of the widget bundle, ADR-0016) for the people who run a shop's
assistant. Today: a placeholder login (pick a role and a tenant, no authentication) and a tenant selector;
the configuration page follows.

```bash
# backend, with the admin API switched on (it does not exist otherwise)
cd backend && ADMIN_API_ENABLED=true uvicorn app.main:app --port 8000
# back office, on http://localhost:5174 (its dev server proxies /api to :8000)
cd backoffice && npm install && npm run dev
npm test && npm run build
```

The admin API sends no CORS headers on purpose, hence the proxy. The buttons follow the
session's permissions, but the API is what enforces them.

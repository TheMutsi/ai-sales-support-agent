# How to add a feature in ai-sales-support-agent

This repo's own way, found in its code. Follow it instead of inventing a structure; when it is wrong, fix this file.

## What this repo uses

<!-- akatsuki:generated:start -->
_Detected from the code by `akatsuki conventions` on 2026-11-16. Rewritten on every run; the recipe below is yours._

### Stack
- **Tests:** next to the code

### How the code is organized
- **Organization:** by type: api
- **Naming:** components in PascalCase files (OrderSummary.tsx)
- **API calls:** centralized in `backoffice/src/api.ts` (1 of 1 calls)
- **Endpoints registered in:** `backend/app/api/admin.py` (5), `backend/app/api/admin_escalations.py` (5), `backend/app/api/auth.py` (5)

### Where things go
| Folder | What lives there | Files | Naming | Example | Tests |
|---|---|---|---|---|---|
| `backend/` | code | 145 | camelCase | `backend/app/db/models.py` | 97 |
| `frontend/` | code | 28 | camelCase | `frontend/src/widget/icons.tsx` | 10 |
| `backoffice/` | code | 11 | camelCase | `backoffice/src/api.ts` | 6 |

### The examples to copy
- **An endpoint:** `GET /login-options` → `backend/app/api/admin.py`
<!-- akatsuki:generated:end -->

## Recipe

<!-- Written by an agent after reading the examples above (skill: repo-recipe), then approved by a human.
     Concrete steps for THIS repo, in order, each naming the file or folder to touch and the example to copy. -->
1. <!-- e.g. Add the endpoint: route in src/routes/orders.ts, handler in src/controllers/…, logic in src/services/… -->

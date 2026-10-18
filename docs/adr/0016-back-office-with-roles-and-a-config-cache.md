# ADR-0016: The back office has roles from the start, a placeholder login, and a cache for tenant configuration

- **Status:** Proposed (agreed with the owner; implementation in progress)
- **Introduced in:** Stage 12 (the back office)

## Context

Everything a shop needs to run the assistant is configured today by editing the database or the
seed: the origins its widget may run on, what each identity level may do, its signing secrets,
where its orders come from, how one-time codes are emailed. And nobody can see what the assistant
said or which conversations were handed to a human. The owner wants a back office to configure
those things and to see the messages and the escalations, and later to answer an escalation from
it or hand it to Zendesk.

Two constraints came with that: the login can wait (a placeholder for now), and the configuration
changes rarely but is read on every request, so it should be cached while staying manageable from
the back office.

## Decision

- **A separate admin API under `/api/admin`, a separate React app (`backoffice/`).** It is not
  part of the widget bundle: the widget ships to other people's pages and must stay small, the
  back office is an application with its own pages.
- **Permissions are checked per action, from the start.** Roles (`viewer`, `agent`, `admin`,
  `operator`) are only bundles of permissions (`config:read`, `config:write`, `conversations:read`,
  `escalations:reply`, `tenants:create`, ...), and every admin endpoint declares the one permission
  it needs, as the chat declares the scope each intent needs (ADR-0014). The authorization is
  therefore built before the authentication that will feed it.
- **The login is a placeholder, and the admin API refuses to exist outside local environments
  while it is.** The entry page says "login pending" and lets the person pick a role; the session
  it gives is a signed token carrying that role. Because that is no authentication at all, the
  admin router is mounted only when `APP_ENV` is local, and "a real back office login" is on the
  before-production list. Replacing the placeholder changes how the role is obtained, not who may
  do what.
- **A tenant selector.** Everything in the back office is scoped to the tenant chosen in a
  combo box; the `operator` role may choose any, and the data of a tenant is never shown under
  another's id.
- **A cache for tenant configuration** (`TenantConfigCache`): origins, scope overrides and the
  identity of a tenant by API key, read through a small in-process cache with a short TTL, and
  **invalidated explicitly when the back office writes**. The origin guard and the scope lookup
  hit the database on every request today, and the CORS layer reads every tenant's origins on
  every preflight.
- **Credentials entered in the back office (an SMTP password, a shop's orders API key) are
  encrypted at rest** with an application key, and are write-only: the back office can replace
  them and shows that one is set, never its value.
- **Order of work:** the admin API and the cache; the back office shell (placeholder login, tenant
  selector, configuration page); secrets and integrations (rotate a signing secret, the orders
  endpoint, SMTP); a viewer of conversations and messages with the identification timeline; an
  inbox of escalations (list, assign, close, reply) behind an interface so Zendesk can be one
  more destination later.

## Consequences

- Adding an admin endpoint means choosing its permission, and a test asserts every route under
  `/api/admin` declares one, so a forgotten check fails a test instead of opening a route.
- The cache is in-process: with several API instances a change reaches the others only after the
  TTL. That bound (tens of seconds) is acceptable for configuration that changes rarely, and the
  writing instance sees its own change at once. A shared cache would remove the delay at the cost
  of a service to run.
- Until the real login exists the back office is a development tool: anyone who can reach it as
  `operator` can read every tenant's messages. The mounting rule keeps it out of a deployment; it
  does not make it safe to expose.
- Reading messages in a back office is access to personal data: viewing is permissioned, and an
  audit of who looked at what is a follow-up.

## Not built yet

Everything above. See the roadmap in `CLAUDE.md`.

## Alternatives

- **Add the pages to the widget bundle.** Ships admin code to every visitor of every shop.
- **A real login first.** Delays everything the owner asked for behind a decision (passwords,
  one-time codes or SSO) that does not change what the back office does.
- **A shared cache (Redis) from the start.** Fixes the delay across instances but adds a service
  for configuration that rarely changes; the in-process cache has the same interface and can be
  swapped.
- **No cache.** Simple, and the origin guard keeps reading every tenant on every request.

## References

- ADR-0014 (scopes and identity), `backend/app/api/origins.py`, `backend/app/api/chat.py`

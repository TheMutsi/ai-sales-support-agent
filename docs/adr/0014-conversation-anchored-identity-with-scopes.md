# ADR-0014: Identity hangs off the conversation, and what a visitor may do is a set of scopes

- **Status:** Accepted
- **Introduced in:** Stage 10a (PRs #62 to #66, #72 to #76, #80 to #87)

## Context

The widget is embedded in a shop's page and talks to this API from the visitor's
browser. The visitor may be a logged-in customer of the shop, someone who has not
logged in, or someone who can prove who they are only by owning an email address. The
browser cannot be trusted with who the customer is, and the agent must not be what
decides what a visitor may see or do: a prompt is not an access control.

## Decision

**Tenant, and how the shop vouches for a customer.**
- A tenant is a shop, with a public `api_key` (it ships in the widget URL, and only
  identifies the tenant) and secrets we issue, each with a `kid` so a shop can rotate
  without downtime.
- The shop's own server signs a short-lived HS256 JWT (`sub` is the shop's id for the
  customer; at most one hour, 30 seconds of leeway; `alg: none` and other algorithms are
  refused) and the widget hands it to `POST /api/auth/login` through a callback. We
  verify it locally: nobody gives us their secret, and we offer no API to encrypt or
  verify tokens. An unknown `sub` is refused; a login never creates a customer.

**The conversation is the anchor.**
- `POST /api/conversations` starts an anonymous conversation. Identifying (the shop's
  token or a one-time code) attaches the customer to *that* conversation, so the history
  carries over. A conversation that already has a customer is never reassigned: someone
  else identifying in the same browser gets a conversation of their own.
- A session is a token we sign (`tid`, `conv`, `lvl`, and `cid` only when identified). It
  proves the conversation is yours and says how you identified; the client never chooses
  `conversation_id` or `customer_id`, and every route compares the id in its path with the
  one in the token.

**What a visitor may do is data: scopes per identity level.**
- Levels: `anonymous` (`kb:read`), `store_login` and `otp_login` (the same scopes: they
  prove the same thing, only how differs), `order_lookup` (read-only, no personal data).
  A tenant can override the scopes of a level. The session does not carry scopes: they
  are resolved on each request from the level and the tenant's overrides, so changing a
  tenant's configuration takes effect without re-issuing tokens.
- Every intent but `unsupported` needs a scope (`agent/permissions.py`), checked in routing as
  a table lookup. When the visitor lacks it, the graph goes to `request_identity`: a fixed text,
  no model call, plus the methods to offer (the levels whose scopes include the missing one). A
  missing list of scopes means none. Rejecting an order needs `refund_request`, a verified
  customer, because it changes what the customer owns. The chat offers `otp` and `order_id`;
  `store_login` is never offered there, because it happens on the shop's page before any form.
  Nodes that act on an account also refuse to run without a customer. An off-topic
  (`unsupported`) message from someone who cannot open a ticket is answered, not escalated.

**One-time codes.**
- `POST /api/auth/otp/request` always answers an empty 202. `POST /api/auth/otp/verify`
  answers a session, or the same 401 `invalid_code` for every failure. The code is six
  digits, valid for ten minutes, five wrong guesses kill it, five sends per email per
  hour, and only an HMAC of it is stored. A malformed email or code is a 422 (its shape
  reveals nothing about accounts).
- Identity inputs are validated strictly, with no validator library, because they come from
  strangers and end up in a query and a log line: an email is a plain local part and a dotted
  domain, an order id is 20 ASCII letters or digits, matched with `fullmatch` (`$` lets a trailing
  newline by) and `[0-9]` (`\d` accepts other scripts' digits). The order's email is compared by
  our code, never by the order source, so the rule holds whoever provides the orders.
- The email and the code never go through the chat: the widget renders a form for the
  methods in the `done` event and calls these endpoints directly, so they stay out of the
  model, the history and the traces.

**Resuming.** The identity request is stored as a message with `kind=identity_request`
(kept out of the model's history, and with no `reply_to_seq`). After identifying, the widget
calls `POST /api/chat/resume`: the pending message is the latest user message before an
identity request that is still the last thing in the conversation, derived from what is
stored, so there is no pending state to expire. It is the same stored message and id, so
nothing is duplicated.

**Around it.** Rate limits per client address on what a stranger can call and per
conversation on the chat (a fixed-window counter in Postgres, `X-Forwarded-For` believed
only for `TRUSTED_PROXY_COUNT` hops from the right). Each tenant lists the origins its
widget runs on: the CORS headers go to an origin any tenant lists (a preflight cannot say
which), and a request is then checked against its own tenant's list.

**Audit record.** Every attempt to identify (a code requested or checked, an order looked up, the
shop's login) writes one row to `identification_events`: how, what came of it and, for a failure,
why (`unknown_customer`, `email_mismatch`, `order_not_found`, `token_expired`...). The reason stays
in the table. For codes and orders the visitor still gets the same generic answer; the shop's
login keeps its existing distinct codes (`token_expired` is how the widget knows to ask the shop
for a fresh token), which are not new information. A row holds the tenant, the
conversation, the customer when a code or the shop's login proved one (never for an order), the
email **masked** (`a***@n***.com`) and an **HMAC** of the email (to group attempts by the same
address) and of an order id (hashed as the visitor typed it, in successes and failures alike). It never holds a code, a token, a full email or a full order id, and
a test scans every column of the rows of every outcome (a success and a failure for each
method) for them. With the identity requests already stored as messages
(`kind=identity_request`), the timeline of a conversation is those messages joined with these rows
by `conversation_id`. Writing a row never decides a login: if it fails, the attempt carries on
and the failure is logged. The caller's session on the code request ties that row to its
conversation. The `security_events` log line now carries the masked email too.

### Hardening, in the code's own terms

- **Store tokens** (`app/auth/store_token.py`): `HS256` is fixed by us, never read from the
  header (`alg: none`). `exp` and `sub` are required, `exp` at most an hour away plus a 30 second
  clock-skew leeway. `kid` picks the secret during a rotation; without one, the only active secret
  is used, and with several the token is rejected as ambiguous. The header is attacker-controlled,
  so an unhashable `kid` is refused before the lookup. Callers get a stable code, never the
  library's message, which would tell a prober which check failed. Tokens can be replayed until
  they expire (a `jti` store would stop that).
- **Login answers do not say what exists.** `invalid_token` covers an unknown API key and a bad
  signature alike, `token_expired` is its own code because the widget can fix it, and
  `customer_not_found` (403) means a genuine token for a customer we do not know: logins never
  create customers. Timing still differs, so the per-IP rate limit is the real defence against
  probing.
- **Sessions** fix the algorithm too, and which identity they name follows from the level: a
  customer for `store_login` and `otp_login`, one order for `order_lookup`, nothing for
  `anonymous`. A claim the level does not take is rejected, not ignored, so an order id can never
  double as a customer.
- **Scopes that act on a customer** can never be granted to a level that proves none, even by a
  tenant override, because the steps behind them would fail. Unknown scope names in an override
  are dropped at request time (a typo must not widen access) and refused when saved from the back
  office.
- **Conversations under a lock.** Attaching a customer locks the conversation row and re-reads it
  under the lock, so two simultaneous logins cannot both take the same anonymous conversation; a
  presented id is used only if it exists in the same tenant. An order lookup never attaches a
  customer, so a later one-time code can still claim the conversation.
- **One-time codes.** A new code replaces any open one. Guesses lock the challenge row, so parallel
  guesses are counted one at a time and a correct code is consumed once. Two customers whose
  emails differ only by case get no code, rather than a guess at who should. The SMTP sender
  refuses to log in over an unencrypted connection, decrypts the password only when sending, and
  a tenant with no mail server outside local environments fails to send rather than logging codes.
- **The audit never decides a login.** A failed write is logged and the attempt carries on, since
  an outage of the audit store must not lock customers out; with no tenant (an unknown API key)
  nothing is written. Emails are masked (`a***@n***.com`) and hashed with a key and a `kind`, so an
  email and an order id never collide, and the order id hashed is the one the visitor typed, so one
  order never gets two hashes. The comparison of the order's email is case-insensitive and in
  constant time. Logs carry the masked address; the security event keeps what a reviewer needs.
  `audit.record` commits the caller's session and rolls it back if the write fails, so a caller
  commits whatever it needs before recording.
- A tenant's secret is 32 bytes from the OS CSPRNG, shown to the shop once; the API key is public.

## Consequences

- The agent never decides access, and a forgotten setting fails closed.
- Any server instance can serve any request: tokens are self-contained and the state is in
  Postgres.
- The origin check is a browser-side defence, not authentication: a script can omit or
  forge `Origin`.
- The audit table has no retention yet: the planned 90 days need the retention job, which is
  not written. Until then it only grows.
- Rate limits are a fixed window (up to twice the limit across a boundary) with no global
  per-tenant budget, and their numbers are estimates with no traffic behind them.
- The shop's token can be replayed until it expires (at most an hour); one-time use would
  need a `jti` and a store of spent ones.
- Tenant secrets are stored in the clear (HS256 needs the raw key); encrypting them at rest
  is a follow-up.

## Not built yet

- `order_lookup` as a way to use the chat. The endpoint exists (`POST /api/auth/order-lookup`:
  an email plus the id of one of its orders, one generic 401 for every failure, a session that
  names that one order and never the customer, and a conversation left unlinked so a one-time
  code can still claim it later); orders come from the async `OrderSource` interface, with a
  simulated table behind it. The agent's `order_status` intent reads that order (the tenant and
  the order id come from the session, never from the message), and the widget form asks for the
  email first and then a code or an order number. Two consequences to know: a customer verified
  with a code or by the shop who asks about an order has no order in the session, so the agent
  reads all of their own orders (the customer comes from the session, never from the message;
  the 10 most recent) and lists them, asking which one they mean when there are several, instead
  of picking one for them; and if a visitor submits the order form, the new session is an
  `order_lookup` one with no customer, so they lose the account scopes until they verify again
  (a narrowing, not a leak).
- A real email provider for the codes (outside local environments sending fails loudly).
- Flagging codes requested and never used, and the retention job that archives old
  messages and purges anonymous conversations.

## Alternatives

- **The shop sends an encrypted customer id.** We would have to hold a key to decrypt it
  and could not tell a forged one from a genuine one; a signed token we verify with the
  shop's secret answers both.
- **An opaque session store.** A lookup on every request and a store to run, for what a
  signed token already carries.
- **The client picks `conversation_id` or `customer_id`.** Anyone could act as anyone.
- **Let the model decide whether to ask for identification.** Not a control: the same
  prompt-injection surface the rest of the design keeps the model out of.

## References

- `backend/app/auth/` (scopes, tokens, login, OTP), `backend/app/api/auth.py`,
  `backend/app/api/deps.py`, `backend/app/api/origins.py`, `backend/app/api/rate_limit.py`
- `backend/app/agent/permissions.py`, `backend/app/agent/nodes/request_identity.py`
- ADR-0013 (the server holds the conversation)

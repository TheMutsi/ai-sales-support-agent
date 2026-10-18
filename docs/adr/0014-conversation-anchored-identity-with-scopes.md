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
- Every intent needs a scope (`agent/permissions.py`), checked in routing as a table
  lookup. When the visitor lacks it, the graph goes to `request_identity`: a fixed text,
  no model call, plus the methods to offer (the levels whose scopes include the missing
  one). A missing list of scopes means none. Nodes that act on an account also refuse to
  run without a customer. An off-topic message from someone who cannot open a ticket is
  answered, not escalated.

**One-time codes.**
- `POST /api/auth/otp/request` always answers an empty 202. `POST /api/auth/otp/verify`
  answers a session, or the same 401 `invalid_code` for every failure. The code is six
  digits, valid for ten minutes, five wrong guesses kill it, five sends per email per
  hour, and only an HMAC of it is stored. A malformed email or code is a 422 (its shape
  reveals nothing about accounts).
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

## Consequences

- The agent never decides access, and a forgotten setting fails closed.
- Any server instance can serve any request: tokens are self-contained and the state is in
  Postgres.
- The origin check is a browser-side defence, not authentication: a script can omit or
  forge `Origin`.
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
  email first and then a code or an order number. Two consequences to know: a customer verified with a code who asks
  about an order has no order in the session, so the agent asks for one and offers only the
  order form; and if they submit it, the new session is an `order_lookup` one with no customer,
  so they lose the account scopes until they verify again (a narrowing, not a leak).
- An audit record of the identification steps (the email asked for, given, and which
  method proved identity), without ever storing the code.
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

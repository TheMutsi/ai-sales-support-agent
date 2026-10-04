---
title: "AcmeFlow Frequently Asked Questions"
doc_type: faq
product_area: general
plan_scope: null
version: "1.0"
---

# AcmeFlow Frequently Asked Questions

> Example KB content for a portfolio demo.

## How do I invite a teammate to my workspace?

From the dashboard, go to Settings → Team, and enter the teammate's work
email. They'll receive an invite link by email; accepting it counts as one
seat against the plan's seat limit.

## What happens if I go over my API call limit?

Requests beyond the plan's monthly API call limit are rejected with a rate-
limit error until the next billing period starts, or until the account
upgrades to a plan with a higher (or unlimited) limit. Usage isn't carried
over or charged per-overage.

## Can I export my data?

Yes. Reports can be exported as CSV from the Reports tab on any plan. A full
account data export (all historical records, not just report views) can be
requested from Settings → Data Export and is delivered by email within 24
hours.

## How do I reset a teammate's password?

Teammates reset their own password from the sign-in page's "Forgot password"
link. A workspace admin cannot reset another user's password directly, for
security reasons — they can only revoke that user's access and re-invite them.

## Is there a mobile app?

Not currently — AcmeFlow is a web dashboard, accessible from a mobile browser
but not published as a native app.

## How do I set up SSO?

SSO (SAML 2.0) is available on the Enterprise plan. Contact AcmeFlow support
to start the setup — it requires exchanging SAML metadata between AcmeFlow and
the company's identity provider, which isn't a self-serve toggle.

## What's the difference between account status and subscription status?

Account status (active, trial, suspended) describes whether a person can sign
in at all. Subscription status (active, past_due, canceled) describes the
commercial state of their plan. A trial account and an active paid account can
both have an "active" subscription status; they're tracked separately so a
billing issue doesn't automatically lock a trial user out, and vice versa.

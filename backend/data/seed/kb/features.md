---
title: "AcmeFlow Features by Plan"
doc_type: features
product_area: product
plan_scope: null
version: "1.0"
---

# AcmeFlow Features by Plan

> Example KB content for a portfolio demo. Feature names here mirror the
> `features` list in `backend/data/seed/plans.json` — exact prices and seat/API
> limits are served from the plans table via a tool, not from this document.

## Basic reporting

Available on every plan (Starter, Pro, Enterprise). Dashboard views for daily
active usage, request volume, and error rate, with a 30-day lookback window.
Exportable as CSV from the Reports tab.

## Advanced reporting

Available on Pro and Enterprise. Adds custom date ranges, saved report
templates, scheduled email delivery of reports, and breakdowns by team or API
key instead of only account-wide totals.

## Email support

Available on every plan. Standard email support with a target first response
time of 2 business days.

## Priority support

Available on Pro and Enterprise. Target first response time drops to 4
business hours on business days, with a dedicated support queue separate from
the standard one.

## Integrations

Available on Pro and Enterprise. Connects AcmeFlow to external tools —see the
Integrations document for the current list of supported providers and setup
steps.

## SSO (single sign-on)

Available on Enterprise only. SAML 2.0-based single sign-on so a company can
manage AcmeFlow access through its own identity provider instead of individual
passwords. Setup requires coordination with AcmeFlow support to configure the
SAML metadata exchange.

## Dedicated account manager

Available on Enterprise only. A named AcmeFlow contact for onboarding,
renewal planning, and escalations, instead of routing every request through
the general support queue.

## Seats and API calls

Starter includes up to 3 seats and 1,000 API calls per billing period; Pro
includes up to 15 seats and 20,000 API calls; Enterprise has no fixed seat or
API call limit. These numbers can change — always confirm the current limit
for a specific customer's plan through the account tools rather than quoting
this document from memory, since plan terms are the one thing here that's
more likely to be updated in the plans table than in this file.

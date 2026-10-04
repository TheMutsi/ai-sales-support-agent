---
title: "AcmeFlow Integrations"
doc_type: integrations
product_area: product
plan_scope: null
version: "1.0"
---

# AcmeFlow Integrations

> Example KB content for a portfolio demo.

Integrations are available on the Pro and Enterprise plans (the `integrations`
feature flag); Starter does not include integration access.

## Slack

Posts a notification to a chosen Slack channel when a report finishes
generating, or when usage crosses a threshold the account configures. Set up
from Settings → Integrations → Slack; requires authorizing AcmeFlow in the
target Slack workspace.

## Webhooks

Outbound webhooks can be configured to POST a JSON payload to a customer-owned
URL on events like `report.completed`, `usage.threshold_reached`, and
`subscription.updated`. Payloads are signed with a per-account secret so the
receiving endpoint can verify authenticity.

## Zapier

AcmeFlow publishes a Zapier app with triggers for the same events webhooks
support, so a customer can connect AcmeFlow to hundreds of other tools without
writing code.

## REST API

A REST API, authenticated with a per-account API key, exposes the same data
available in the dashboard (usage, reports, team membership) for programmatic
access. API calls count against the plan's monthly API call limit, same as
any other usage.

## CRM integrations

Native, two-way sync with Salesforce and HubSpot is available on Enterprise.
It keeps account and usage data visible on the customer's CRM record without
manual export/import.

---
title: "AcmeFlow Security Overview"
doc_type: security
product_area: security
plan_scope: null
version: "1.0"
---

# AcmeFlow Security Overview

> Example KB content for a portfolio demo — not a real compliance attestation.
> Don't present any claim in this document as an actual certification.

## Encryption

Data is encrypted in transit (TLS 1.2+) between the customer's browser or API
client and AcmeFlow, and at rest in the production database using the cloud
provider's standard disk-level encryption.

## Access controls

Workspace access is role-based: admins can manage billing, team membership,
and integrations; members can view and generate reports but not change
billing or team settings. Enterprise accounts can additionally enforce SSO
(see the FAQ and Features documents), which centralizes access control through
the customer's own identity provider.

## Audit logs

Enterprise accounts have access to an audit log of admin-level actions
(team membership changes, billing changes, API key creation/revocation),
retained for 12 months and exportable as CSV.

## Data isolation

Each customer's data is logically isolated by account ID at the database
layer — there is no customer-facing feature that queries or displays data
across accounts.

## Incident response

AcmeFlow notifies affected customers by email of any confirmed security
incident involving their data, as soon as it's been verified, consistent with
applicable breach-notification law. This KB entry doesn't track incident
status for a specific account — an active incident is communicated directly,
not looked up here.

## Vulnerability reporting

Security researchers can report a suspected vulnerability to
security@acmeflow.example. This is a support-agent knowledge base, not the
right channel to receive or triage a live vulnerability report — if a message
reads as an actual vulnerability disclosure rather than a general question
about security practices, it should be escalated to a human rather than
answered inline.

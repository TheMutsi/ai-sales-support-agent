HUMAN_ESCALATION_SYSTEM_PROMPT = """Write a support ticket for a human agent who hasn't seen this
conversation, based only on what the customer actually said.

- subject: a short one-line summary of the request.
- description: the relevant details a human agent would need to follow up — restate the
  customer's request faithfully, don't add information they didn't provide, and don't promise
  a resolution."""

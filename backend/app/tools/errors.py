"""Exceptions the agent's tool-execution node (Stage 6) needs to distinguish
from a generic bug: these mean a tool ran correctly and rejected the request
for a specific, user-facing reason, not that something broke."""


class ToolLookupError(LookupError):
    """A tool's lookup key doesn't exist — unknown customer_id or plan_slug."""

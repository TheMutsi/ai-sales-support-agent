"""Exceptions the agent's tool-execution node (Stage 6) needs to distinguish
from a generic bug: these mean a tool ran correctly and rejected the request
for a specific, user-facing reason, not that something broke."""


class ToolLookupError(LookupError):
    """A tool's lookup key doesn't exist — unknown customer_id or plan_slug."""


class UpgradeNotEligibleError(Exception):
    """`create_upgrade_checkout` refused: the guardrail in CLAUDE.md ("never
    create a checkout unless eligibility was actually checked") is enforced
    here, not left to the agent to remember to check first."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)

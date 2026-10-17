"""What an intent needs from the visitor's identity, as data.

The check is a table lookup in `routing.py`, never the model's judgment: whether
someone may see an account or open a ticket is not something to leave to a prompt.
Which way of identifying to offer follows from the scope that is missing: the levels
that grant it.
"""

from app.auth.scopes import IdentityLevel, Scope, scopes_for
from app.schemas.agent import Intent

# `unsupported` is absent on purpose: it needs no identity to be answered, and routing
# opens a ticket for it only when the visitor could open one.
REQUIRED_SCOPE: dict[Intent, Scope] = {
    Intent.PRODUCT_QUESTION: Scope.KB_READ,
    Intent.PRICING_QUESTION: Scope.KB_READ,
    Intent.TECHNICAL_SUPPORT: Scope.KB_READ,
    Intent.SMALL_TALK: Scope.KB_READ,
    Intent.BILLING_QUESTION: Scope.CUSTOMER_READ,
    Intent.UPGRADE_REQUEST: Scope.CUSTOMER_READ,
    Intent.REFUND_REQUEST: Scope.REFUND_REQUEST,
    Intent.HUMAN_ESCALATION: Scope.TICKET_CREATE,
}

# The ways the widget can identify someone in the chat. `store_login` is not one: it
# happens on the shop's page, before any form.
_CHAT_METHODS = ((IdentityLevel.OTP_LOGIN, "otp"), (IdentityLevel.ORDER_LOOKUP, "order_id"))


def identity_methods_for(scope: Scope, overrides: dict | None) -> list[str]:
    return [
        method
        for level, method in _CHAT_METHODS
        if scope in scopes_for(level, overrides)
    ]

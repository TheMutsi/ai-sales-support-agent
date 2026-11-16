from app.auth.scopes import IdentityLevel, Scope, scopes_for
from app.schemas.agent import Intent

REQUIRED_SCOPE: dict[Intent, Scope] = {
    Intent.PRODUCT_QUESTION: Scope.KB_READ,
    Intent.PRICING_QUESTION: Scope.KB_READ,
    Intent.TECHNICAL_SUPPORT: Scope.KB_READ,
    Intent.SMALL_TALK: Scope.KB_READ,
    Intent.BILLING_QUESTION: Scope.CUSTOMER_READ,
    Intent.UPGRADE_REQUEST: Scope.CUSTOMER_READ,
    Intent.REFUND_REQUEST: Scope.REFUND_REQUEST,
    Intent.HUMAN_ESCALATION: Scope.TICKET_CREATE,
    Intent.ORDER_STATUS: Scope.ORDER_READ,
    Intent.ORDER_RETURN: Scope.REFUND_REQUEST,
}

_CHAT_METHODS = ((IdentityLevel.OTP_LOGIN, "otp"), (IdentityLevel.ORDER_LOOKUP, "order_id"))


def identity_methods_for(scope: Scope, overrides: dict | None) -> list[str]:
    return [
        method
        for level, method in _CHAT_METHODS
        if scope in scopes_for(level, overrides)
    ]

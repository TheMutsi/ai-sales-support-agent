"""The record of one turn of a return, built from the state the graph ended with.

Only what a step really did is recorded (its outcome, what it offered, what was recorded), never
what a model said, and no free text: the visitor's words stay in `messages`. See `ReturnEvent`.
"""

from app.chat.turns import TurnStart
from app.schemas.orders import ReturnResult


def build_return_event(
    final_state: dict,
    *,
    turn: TurnStart,
    tenant_id,
    conversation_id,
    customer_id,
    identity_level: str,
    model: str,
    app_version: str,
    duration_ms: int,
) -> dict | None:
    """The columns of a `ReturnEvent`, or None when this turn did not go through `order_return`."""
    result: ReturnResult | None = final_state.get("return_result")
    if result is None:
        return None
    order, offer, receipt = result.order, result.offer, result.receipt
    before, after = turn.pending_return, final_state.get("pending_return")
    reading = final_state.get("return_reading")
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "identity_level": identity_level,
        "user_seq": turn.user_seq,
        "input_type": "action" if turn.click is not None else "text",
        "action": turn.click.value if turn.click is not None else None,
        "action_order_id": turn.click_order_id,
        "reading": reading.value if reading is not None else None,
        "stage_before": before.stage.value if before else None,
        "stage_after": after.stage.value if after else None,
        "outcome": result.outcome.value,
        "order_id": order.order_id if order else None,
        "order_status": order.status.value if order else None,
        "order_amount_cents": order.amount_cents if order else None,
        "candidates": len(result.candidates),
        "offer_refund_cents": offer.refund_cents if offer else None,
        "offer_credit_cents": offer.credit_cents if offer else None,
        "taken_refund_cents": receipt.refund_cents if receipt else None,
        "taken_credit_cents": receipt.credit_cents if receipt else None,
        "gift": receipt.gift if receipt else None,
        "model": model,
        "app_version": app_version,
        "duration_ms": duration_ms,
    }

"""Which orders source the app uses. One place, so the agent and the identity endpoint agree."""

from app.db.session import SessionLocal
from app.orders.simulated import SimulatedOrderSource
from app.orders.source import OrderSource


def get_order_source() -> OrderSource:
    """The shop's orders. A simulated table until the shop's own API is wired in."""
    return SimulatedOrderSource(SessionLocal)

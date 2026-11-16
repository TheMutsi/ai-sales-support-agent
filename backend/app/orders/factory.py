from app.db.session import SessionLocal
from app.orders.simulated import SimulatedOrderSource
from app.orders.source import OrderSource


def get_order_source() -> OrderSource:
    return SimulatedOrderSource(SessionLocal)

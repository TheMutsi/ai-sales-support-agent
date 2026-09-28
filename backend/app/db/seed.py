"""Populate plans, customers, and subscriptions from the fixtures in `data/seed/`.

Documents, tickets, and evaluation runs are intentionally left empty here — they're
produced by later stages (RAG ingestion, live agent runs, the evaluation suite), not
by this fixture load.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Customer, Plan, Subscription
from app.db.session import SessionLocal

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


def _load(name: str) -> list[dict]:
    return json.loads((SEED_DIR / name).read_text())


def seed(db: Session) -> None:
    plans_by_slug = {p.slug: p for p in db.query(Plan).all()}
    for entry in _load("plans.json"):
        if entry["slug"] in plans_by_slug:
            continue
        plan = Plan(**entry)
        db.add(plan)
        plans_by_slug[plan.slug] = plan
    db.flush()

    existing_emails = {c.email for c in db.query(Customer).all()}
    now = datetime.now(UTC)
    for entry in _load("customers.json"):
        if entry["email"] in existing_emails:
            continue
        customer = Customer(
            name=entry["name"],
            email=entry["email"],
            company=entry["company"],
            status=entry["status"],
        )
        db.add(customer)
        db.flush()

        canceled_at = None
        if "canceled_days_ago" in entry:
            canceled_at = now - timedelta(days=entry["canceled_days_ago"])

        db.add(
            Subscription(
                customer_id=customer.id,
                plan_id=plans_by_slug[entry["plan_slug"]].id,
                status=entry["subscription_status"],
                current_period_end=now + timedelta(days=entry["period_days_from_now"]),
                canceled_at=canceled_at,
            )
        )

    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
        print("Seed complete.")

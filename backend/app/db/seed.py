import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import LOCAL_ENVIRONMENTS, get_settings
from app.db.models import (
    Conversation,
    Customer,
    Order,
    OrderAdjustment,
    Plan,
    Subscription,
    Tenant,
    TenantSecret,
)
from app.db.session import SessionLocal

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


DEV_TENANT_API_KEY = "pk_dev_mewflow_local"
DEV_TENANT_SECRET = "dev-only-tenant-secret-never-use-in-production"
DEV_TENANT_ORIGINS = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8081",
]
DEV_TENANT_KID = "dev-1"


def _load(name: str) -> list[dict]:
    return json.loads((SEED_DIR / name).read_text())


def _ensure_dev_tenant(db: Session) -> Tenant | None:
    if get_settings().app_env not in LOCAL_ENVIRONMENTS:
        return None
    tenant = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one_or_none()
    if tenant is None:
        tenant = Tenant(name="Local development shop", api_key=DEV_TENANT_API_KEY)
        db.add(tenant)
        db.flush()
    tenant.allowed_origins = DEV_TENANT_ORIGINS
    secret = db.query(TenantSecret).filter_by(tenant_id=tenant.id, kid=DEV_TENANT_KID).one_or_none()
    if secret is None:
        db.add(TenantSecret(tenant_id=tenant.id, kid=DEV_TENANT_KID, secret=DEV_TENANT_SECRET))
    else:
        secret.secret, secret.active = DEV_TENANT_SECRET, True
    return tenant


def seed(db: Session) -> None:
    plans_by_slug = {p.slug: p for p in db.query(Plan).all()}
    for entry in _load("plans.json"):
        if entry["slug"] in plans_by_slug:
            continue
        plan = Plan(**entry)
        db.add(plan)
        plans_by_slug[plan.slug] = plan
    db.flush()

    tenant = _ensure_dev_tenant(db)
    tenant_id = tenant.id if tenant else None
    existing = {
        c.email: c
        for c in db.query(Customer).filter(
            (Customer.tenant_id == tenant_id) | (Customer.tenant_id.is_(None))
        )
    }
    now = datetime.now(UTC)
    for entry in _load("customers.json"):
        if entry["email"] in existing:
            customer = existing[entry["email"]]
            if tenant and customer.tenant_id is None:
                customer.tenant_id, customer.external_id = tenant_id, customer.email
            continue
        customer = Customer(
            name=entry["name"],
            email=entry["email"],
            company=entry["company"],
            status=entry["status"],
            tenant_id=tenant_id,
            external_id=entry["email"] if tenant else None,
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

    db.flush()
    _ensure_orders(db, plans_by_slug, tenant_id)
    if tenant:
        _ensure_demo_shop(db, plans_by_slug, tenant_id, now)
    db.commit()


DEMO_ITEM = {
    "name": "Shapermint Essentials High-Waisted Shaping Leggings x2",
    "images": [
        "https://cdn.shopify.com/s/files/1/0021/4889/2732/files/01_42075_PDP.jpg?v=1773936617",
        "https://cdn.shopify.com/s/files/1/0021/4889/2732/files/06_42075_PDP.jpg?v=1773936617",
    ],
}

DEMO_SHOP = [
    {"email": "mail1@gmail.com", "status": "open", "amount_cents": 2999},
    {"email": "mail2@gmail.com", "status": "open", "amount_cents": 6999},
    {"email": "mail3@gmail.com", "status": "in_delivery", "amount_cents": 6999},
    {"email": "mail4@gmail.com", "status": "in_delivery", "amount_cents": 2999},
]


def _demo_plan(plans: dict[str, Plan], amount_cents: int) -> Plan:
    return plans["pro" if amount_cents >= 5000 else "starter"]


def _ensure_demo_shop(db: Session, plans: dict[str, Plan], tenant_id, now: datetime) -> None:
    have = {
        c.email: c
        for c in db.query(Customer).filter(
            (Customer.tenant_id == tenant_id) | (Customer.tenant_id.is_(None))
        )
    }
    for number, entry in enumerate(DEMO_SHOP, start=1):
        customer = have.get(entry["email"])
        if customer is not None and customer.tenant_id is None:
            customer.tenant_id, customer.external_id = tenant_id, customer.email
        if customer is None:
            customer = Customer(
                name=f"Demo User {number}", email=entry["email"], company="Demo shop",
                status="active", tenant_id=tenant_id, external_id=entry["email"],
            )
            db.add(customer)
            db.flush()
            db.add(
                Subscription(
                    customer_id=customer.id, plan_id=plans["starter"].id, status="active",
                    current_period_end=now + timedelta(days=20),
                )
            )
        order_id = _order_id(customer.email)
        if db.query(Order).filter_by(order_id=order_id).one_or_none() is None:
            db.add(
                Order(
                    order_id=order_id, customer_id=customer.id,
                    plan_id=_demo_plan(plans, entry["amount_cents"]).id,
                    item_name=DEMO_ITEM["name"], item_images=DEMO_ITEM["images"],
                    amount_cents=entry["amount_cents"], status=entry["status"],
                    created_at=now - timedelta(days=2),
                )
            )


def _order_id(email: str) -> str:
    return hashlib.sha256(f"order:{email}".encode()).hexdigest()[:20]


def _ensure_orders(db: Session, plans_by_slug: dict[str, Plan], tenant_id) -> None:
    now = datetime.now(UTC)
    have = {o.order_id for o in db.query(Order)}
    entries = {e["email"]: e for e in _load("customers.json")}
    customers = db.query(Customer).filter(Customer.email.in_(entries), Customer.tenant_id == tenant_id)
    for customer in customers:
        entry = entries[customer.email]
        order_id = _order_id(customer.email)
        if order_id in have:
            continue
        plan = plans_by_slug[entry["plan_slug"]]
        status = {"past_due": "pending", "canceled": "refunded"}.get(
            entry["subscription_status"], "paid"
        )
        db.add(
            Order(
                order_id=order_id,
                customer_id=customer.id,
                plan_id=plan.id,
                amount_cents=plan.price_cents,
                status=status,
                created_at=now - timedelta(days=30),
            )
        )


def reset_demo_shop(db: Session) -> int:
    if get_settings().app_env not in LOCAL_ENVIRONMENTS:
        raise RuntimeError("the demo shop exists only in local environments")
    tenant = db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one_or_none()
    if tenant is None:
        return 0
    plans = {p.slug: p for p in db.query(Plan)}
    emails = [entry["email"] for entry in DEMO_SHOP]
    wanted = {_order_id(entry["email"]): entry for entry in DEMO_SHOP}
    orders = (
        db.query(Order)
        .join(Customer, Order.customer_id == Customer.id)
        .filter(Order.order_id.in_(wanted), Customer.tenant_id == tenant.id)
        .all()
    )
    for order in orders:
        db.query(OrderAdjustment).filter_by(order_id=order.id).delete()
        order.status = wanted[order.order_id]["status"]
        order.amount_cents = wanted[order.order_id]["amount_cents"]
        order.plan_id = _demo_plan(plans, order.amount_cents).id
        order.item_name, order.item_images = DEMO_ITEM["name"], DEMO_ITEM["images"]
    customer_ids = [
        c.id
        for c in db.query(Customer).filter(Customer.email.in_(emails), Customer.tenant_id == tenant.id)
    ]
    db.query(Conversation).filter(Conversation.customer_id.in_(customer_ids)).update(
        {"pending_return_order_id": None, "pending_return_stage": None, "pending_return_at": None}
    )
    db.commit()
    return len(orders)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load the seed data.")
    parser.add_argument("--reset-demo", action="store_true", help="put the demo shop's orders back")
    arguments = parser.parse_args()
    with SessionLocal() as session:
        seed(session)
        if arguments.reset_demo:
            print(f"Demo orders reset: {reset_demo_shop(session)}.")
        print("Seed complete.")

"""Populate plans, customers, and subscriptions from the fixtures in `data/seed/`.

Documents, tickets, and evaluation runs are intentionally left empty here — they're
produced by later stages (RAG ingestion, live agent runs, the evaluation suite), not
by this fixture load.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import LOCAL_ENVIRONMENTS, get_settings
from app.db.models import Customer, Plan, Subscription, Tenant, TenantSecret
from app.db.session import SessionLocal

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"


# A fixed dev tenant so a local token can be signed without any setup: the secret
# is public (it's right here), so it is only ever written in local environments.
DEV_TENANT_API_KEY = "pk_dev_mewflow_local"
DEV_TENANT_SECRET = "dev-only-tenant-secret-never-use-in-production"
# Where the example page runs when served locally (`python -m http.server 8080`). A page
# opened as a file has the origin "null", which is never allowed.
DEV_TENANT_ORIGINS = ["http://localhost:8080", "http://127.0.0.1:8080"]
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
    # Checked on every run, not just when the tenant is created: a dev secret that
    # was deleted or deactivated (say, while trying out rotation) comes back.
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
    # Emails are unique per tenant, so only the dev tenant's customers (and orphans
    # from before tenants existed) count as already seeded; another shop's customer
    # with the same email is a different person.
    existing = {
        c.email: c
        for c in db.query(Customer).filter(
            (Customer.tenant_id == tenant_id) | (Customer.tenant_id.is_(None))
        )
    }
    now = datetime.now(UTC)
    for entry in _load("customers.json"):
        if entry["email"] in existing:
            # Customers seeded before the dev tenant existed get linked to it.
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

    db.commit()


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
        print("Seed complete.")

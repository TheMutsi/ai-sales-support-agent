"""Integration tests for `list_customers` (the data behind the frontend's
customer selector) and `GET /api/customers`.

Requires a real Postgres (`alembic upgrade head`) — the `seeded_db` fixture
(conftest.py) loads the sample customers from `data/seed/`.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.tools.customers import list_customers
from tests.integration.conftest import customer_by_email

client = TestClient(app)


def test_lists_every_seeded_customer_with_their_current_plan(seeded_db: Session):
    priya = customer_by_email(seeded_db, "priya.anand@bluecrestlogistics.com")

    customers = list_customers()

    by_id = {c.customer_id: c for c in customers}
    assert len(customers) == seeded_db.query(type(priya)).count()
    assert by_id[priya.id].name == "Priya Anand"
    assert by_id[priya.id].plan_slug == "pro"
    assert by_id[priya.id].status == "active"


def test_customers_are_sorted_by_name(seeded_db: Session):
    names = [c.name for c in list_customers()]

    assert names == sorted(names)


def test_endpoint_returns_the_same_list(seeded_db: Session):
    response = client.get("/api/customers")

    assert response.status_code == 200
    body = response.json()
    assert [c["name"] for c in body] == [c.name for c in list_customers()]
    assert set(body[0]) == {"customer_id", "name", "company", "status", "plan_slug", "plan_name"}
    # The selector is not a data export: no email, no billing detail.
    assert "email" not in body[0]

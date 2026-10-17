import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.credentials import generate_api_key
from app.db.models import Customer, Tenant
from app.db.session import SessionLocal


@pytest.fixture
def two_tenants(tenant_wipe):
    with SessionLocal() as db:
        a = Tenant(name="Shop A", api_key=generate_api_key())
        b = Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all([a, b])
        db.commit()
        yield a.id, b.id


def test_two_tenants_can_each_have_a_customer_with_the_same_email(two_tenants):
    a, b = two_tenants
    with SessionLocal() as db:
        db.add(Customer(name="Ana", email="ana@x.test", tenant_id=a, external_id="1"))
        db.add(Customer(name="Ana", email="ana@x.test", tenant_id=b, external_id="1"))
        db.commit()

        assert db.query(Customer).filter_by(email="ana@x.test").count() == 2


def test_one_tenant_cannot_repeat_an_email_or_an_external_id(two_tenants):
    a, _ = two_tenants
    with SessionLocal() as db:
        db.add(Customer(name="Ana", email="ana@x.test", tenant_id=a, external_id="1"))
        db.commit()

        db.add(Customer(name="Ana 2", email="ana@x.test", tenant_id=a, external_id="2"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        db.add(Customer(name="Bea", email="bea@x.test", tenant_id=a, external_id="1"))
        with pytest.raises(IntegrityError):
            db.commit()

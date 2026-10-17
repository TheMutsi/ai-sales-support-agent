"""The evaluation runner talks to the real API, so it logs in as each dataset
customer the way the widget would: with a session for that customer."""

import pytest

from app.auth.session import verify_session_token
from app.core.config import get_settings
from app.db.models import Customer, Tenant
from app.db.seed import DEV_TENANT_API_KEY
from evaluation.run_eval import resolve_session_tokens
from tests.integration.conftest import customer_by_email

EMAIL = "ava.chen@northlightstudio.com"


def test_each_email_gets_a_session_for_that_customer(seeded_db):
    tokens = resolve_session_tokens(seeded_db, [EMAIL])

    claims = verify_session_token(tokens[EMAIL], get_settings().session_signing_key)
    customer = customer_by_email(seeded_db, EMAIL)
    assert claims.customer_id == customer.id
    assert claims.tenant_id == customer.tenant_id


def test_an_unknown_email_fails_the_run_before_it_starts(seeded_db):
    with pytest.raises(ValueError, match="nobody@nowhere.test"):
        resolve_session_tokens(seeded_db, [EMAIL, "nobody@nowhere.test"])


def test_a_customer_outside_the_dev_tenant_is_reported_as_unseeded(seeded_db):
    seeded_db.query(Customer).filter_by(email=EMAIL).update({"tenant_id": None})
    seeded_db.commit()

    with pytest.raises(ValueError, match="dev tenant"):
        resolve_session_tokens(seeded_db, [EMAIL])


def test_another_tenants_customer_with_the_same_email_is_never_signed_for(seeded_db):
    """Emails are unique per tenant, so the runner must pick the dev tenant's row
    deliberately and not whichever one the query happens to return last."""
    other = Tenant(name="Other shop", api_key="pk_other")
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(Customer(name="Ava", email=EMAIL, tenant_id=other.id))
    seeded_db.commit()

    tokens = resolve_session_tokens(seeded_db, [EMAIL])

    claims = verify_session_token(tokens[EMAIL], get_settings().session_signing_key)
    dev = seeded_db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one()
    assert claims.tenant_id == dev.id

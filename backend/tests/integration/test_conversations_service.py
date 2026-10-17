"""A conversation is the anchor for who is talking: it starts anonymous and gets a
customer when the visitor identifies. A customer already attached is never
overwritten; the newcomer gets a conversation of their own."""

import threading
import time
import uuid
from datetime import UTC, datetime

import pytest

from app.auth.conversations import create_anonymous, resolve_for_login
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.db.models import Conversation, Customer, SecurityEvent, Tenant
from app.db.session import SessionLocal

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tenant_wipe):
    with SessionLocal() as session:
        yield session


def _tenant(db, name="Shop") -> Tenant:
    tenant = Tenant(name=name, api_key=generate_api_key())
    db.add(tenant)
    db.flush()
    return tenant


def _customer(db, tenant, email) -> Customer:
    customer = Customer(name=email, email=email, tenant_id=tenant.id, external_id=email)
    db.add(customer)
    db.flush()
    return customer


def _login(db, tenant, customer, conversation_id=None, level=IdentityLevel.STORE_LOGIN):
    return resolve_for_login(
        db,
        tenant_id=tenant.id,
        customer_id=customer.id,
        level=level,
        conversation_id=conversation_id,
        now=NOW,
    )


def test_an_anonymous_conversation_has_no_customer(db):
    tenant = _tenant(db)

    conversation = create_anonymous(db, tenant_id=tenant.id, now=NOW)

    assert conversation.customer_id is None
    assert conversation.identity_level == "anonymous"
    assert conversation.last_activity_at == conversation.created_at


def test_identifying_attaches_the_customer_to_the_same_conversation(db):
    tenant = _tenant(db)
    ana = _customer(db, tenant, "ana@shop.test")
    anonymous = create_anonymous(db, tenant_id=tenant.id, now=NOW)

    conversation = _login(db, tenant, ana, anonymous.id, IdentityLevel.OTP_LOGIN)

    assert conversation.id == anonymous.id
    assert conversation.customer_id == ana.id
    assert conversation.identity_level == "otp_login"
    assert conversation.linked_via == "otp_login"
    assert conversation.customer_linked_at is not None


def test_identifying_twice_as_the_same_customer_keeps_the_conversation(db):
    tenant = _tenant(db)
    ana = _customer(db, tenant, "ana@shop.test")
    first = _login(db, tenant, ana, create_anonymous(db, tenant_id=tenant.id, now=NOW).id)

    assert _login(db, tenant, ana, first.id).id == first.id


def test_a_second_customer_never_takes_over_an_attached_conversation(db):
    tenant = _tenant(db)
    ana, bea = _customer(db, tenant, "ana@shop.test"), _customer(db, tenant, "bea@shop.test")
    anas = _login(db, tenant, ana, create_anonymous(db, tenant_id=tenant.id, now=NOW).id)

    beas = _login(db, tenant, bea, anas.id)

    assert beas.id != anas.id and beas.customer_id == bea.id
    db.refresh(anas)
    assert anas.customer_id == ana.id


@pytest.mark.parametrize("known", [False, True])
def test_a_conversation_that_isnt_usable_starts_a_new_one(db, known):
    """Unknown id, or one that belongs to another tenant: never attached to."""
    tenant, other = _tenant(db), _tenant(db, "Other")
    ana = _customer(db, tenant, "ana@shop.test")
    foreign = create_anonymous(db, tenant_id=other.id, now=NOW)
    wanted = foreign.id if known else None

    conversation = _login(db, tenant, ana, wanted)

    assert conversation.customer_id == ana.id and conversation.tenant_id == tenant.id
    assert conversation.id != foreign.id
    db.refresh(foreign)
    assert foreign.customer_id is None


def test_two_customers_identifying_at_once_cannot_both_take_the_same_conversation(db):
    tenant = _tenant(db)
    ana, bea = _customer(db, tenant, "ana@shop.test"), _customer(db, tenant, "bea@shop.test")
    anonymous = create_anonymous(db, tenant_id=tenant.id, now=NOW)
    db.commit()
    done = {}

    def bea_logs_in():
        with SessionLocal() as other:
            done["bea"] = _login(other, tenant, bea, anonymous.id).id

    with SessionLocal() as holder:  # Ana is mid-login: she holds the row lock
        locked = holder.query(Conversation).filter_by(id=anonymous.id).with_for_update().one()
        thread = threading.Thread(target=bea_logs_in)
        thread.start()
        time.sleep(0.3)
        assert thread.is_alive(), "Bea's login should wait for Ana's lock"
        locked.customer_id, locked.identity_level = ana.id, "store_login"
        holder.commit()
    thread.join(timeout=5)

    assert done["bea"] != anonymous.id


def test_a_login_never_discards_what_the_caller_had_pending(db):
    """The caller may have marked a one-time code as used and not committed yet; a
    stale conversation id must not roll that back."""
    tenant = _tenant(db)
    ana = _customer(db, tenant, "ana@shop.test")
    db.add(SecurityEvent(tenant_id=tenant.id, kind="pending_work", email=ana.email))

    _login(db, tenant, ana, uuid.uuid4())  # an id that doesn't exist

    assert db.query(SecurityEvent).filter_by(kind="pending_work").count() == 1


def test_a_conversation_already_loaded_in_the_session_is_checked_against_the_database(db):
    """Without refreshing, the cached row still says 'no customer' after another
    transaction attached one, and the second customer would overwrite the first."""
    tenant = _tenant(db)
    ana, bea = _customer(db, tenant, "ana@shop.test"), _customer(db, tenant, "bea@shop.test")
    anonymous = create_anonymous(db, tenant_id=tenant.id, now=NOW)
    cached = db.get(Conversation, anonymous.id)  # loaded here, never expired
    assert cached.customer_id is None
    with SessionLocal() as other:
        _login(other, tenant, ana, anonymous.id)

    beas = _login(db, tenant, bea, anonymous.id)

    assert beas.id != anonymous.id
    with SessionLocal() as check:
        assert check.get(Conversation, anonymous.id).customer_id == ana.id

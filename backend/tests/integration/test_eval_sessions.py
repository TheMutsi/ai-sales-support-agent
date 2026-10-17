"""The evaluation runner logs in as a client would, in a conversation of its own per case and
per repetition, so one run never sees another's messages as history."""

import pytest

from app.auth.scopes import IdentityLevel
from app.auth.session import verify_session_token
from app.chat.turns import list_messages
from app.core.config import get_settings
from app.db.models import Conversation, Customer, Tenant
from app.db.seed import DEV_TENANT_API_KEY
from evaluation.schemas import EvalCase, EvalIdentity, EvalScenario
from evaluation.sessions import CaseSessions
from tests.integration.conftest import customer_by_email

EMAIL = "ava.chen@northlightstudio.com"


def _case(messages=None, email=EMAIL, case_id="c1") -> EvalCase:
    return EvalCase(
        id=case_id,
        scenario=EvalScenario.PRODUCT_QUESTION,
        customer_email=email,
        messages=messages or [{"role": "user", "content": "Which plan am I on?"}],
    )


def _claims(session):
    return verify_session_token(session.token, get_settings().session_signing_key)

def test_a_case_gets_a_session_in_a_conversation_attached_to_its_customer(seeded_db):
    session = CaseSessions(seeded_db, [EMAIL]).open(_case())

    claims = _claims(session)
    customer = customer_by_email(seeded_db, EMAIL)
    assert claims.customer_id == customer.id and claims.tenant_id == customer.tenant_id
    assert claims.conversation_id == session.conversation_id
    assert seeded_db.get(Conversation, session.conversation_id).customer_id == customer.id


def test_every_opening_of_the_same_case_is_a_fresh_conversation(seeded_db):
    sessions = CaseSessions(seeded_db, [EMAIL])

    first, second = sessions.open(_case()), sessions.open(_case())

    assert first.conversation_id != second.conversation_id


def test_the_messages_before_the_last_one_are_stored_as_the_history(seeded_db):
    case = _case(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "and pricing?"},
        ]
    )

    session = CaseSessions(seeded_db, [EMAIL]).open(case)

    stored = list_messages(seeded_db, conversation_id=session.conversation_id)
    assert [(m.seq, m.role, m.content, m.reply_to_seq) for m in stored] == [
        (1, "user", "hello", None),
        (2, "assistant", "Hi there", 1),
    ]  # the last message is the one the runner sends
    assert seeded_db.get(Conversation, session.conversation_id).last_seq == 2


def test_an_unknown_email_fails_the_run_before_it_starts(seeded_db):
    with pytest.raises(ValueError, match="nobody@nowhere.test"):
        CaseSessions(seeded_db, [EMAIL, "nobody@nowhere.test"])


def test_a_customer_outside_the_dev_tenant_is_reported_as_unseeded(seeded_db):
    seeded_db.query(Customer).filter_by(email=EMAIL).update({"tenant_id": None})
    seeded_db.commit()

    with pytest.raises(ValueError, match="dev tenant"):
        CaseSessions(seeded_db, [EMAIL])


def test_another_tenants_customer_with_the_same_email_is_never_used(seeded_db):
    other = Tenant(name="Other shop", api_key="pk_other")
    seeded_db.add(other)
    seeded_db.flush()
    seeded_db.add(Customer(name="Ava", email=EMAIL, tenant_id=other.id))
    seeded_db.commit()

    claims = _claims(CaseSessions(seeded_db, [EMAIL]).open(_case()))

    dev = seeded_db.query(Tenant).filter_by(api_key=DEV_TENANT_API_KEY).one()
    assert claims.tenant_id == dev.id


def _anonymous_case(messages=None) -> EvalCase:
    return EvalCase(
        id="anon",
        scenario=EvalScenario.PRODUCT_QUESTION,
        identity=EvalIdentity.ANONYMOUS,
        messages=messages or [{"role": "user", "content": "Do you integrate with Salesforce?"}],
    )


def test_an_anonymous_case_gets_an_anonymous_session_with_no_customer(seeded_db):
    session = CaseSessions(seeded_db, []).open(_anonymous_case())

    claims = _claims(session)
    assert claims.customer_id is None and claims.level is IdentityLevel.ANONYMOUS
    assert seeded_db.get(Conversation, session.conversation_id).customer_id is None


def test_an_anonymous_case_keeps_its_earlier_messages_as_history(seeded_db):
    case = _anonymous_case(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "and pricing?"},
        ]
    )

    session = CaseSessions(seeded_db, []).open(case)

    stored = list_messages(seeded_db, conversation_id=session.conversation_id)
    assert [m.content for m in stored] == ["hello", "Hi there"]

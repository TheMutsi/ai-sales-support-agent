"""The back office decides per action. These tests pin the role table and keep an admin token and
a chat session from standing in for each other."""

import uuid
from datetime import timedelta
from itertools import pairwise

import pytest

from app.admin.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    can_access_tenant,
)
from app.admin.session import AdminSessionError, issue_admin_token, verify_admin_token
from app.auth.scopes import IdentityLevel
from app.auth.session import SessionError, issue_session_token, verify_session_token

KEY = "k" * 40


def test_each_role_adds_to_the_one_before():
    order = [Role.VIEWER, Role.AGENT, Role.ADMIN, Role.OPERATOR]
    for lower, higher in pairwise(order):
        assert ROLE_PERMISSIONS[lower] < ROLE_PERMISSIONS[higher]


@pytest.mark.parametrize(
    ("role", "permission", "allowed"),
    [
        (Role.VIEWER, Permission.CONFIG_READ, True),
        (Role.VIEWER, Permission.CONFIG_WRITE, False),
        (Role.VIEWER, Permission.ESCALATIONS_REPLY, False),
        (Role.AGENT, Permission.ESCALATIONS_REPLY, True),
        (Role.AGENT, Permission.CONFIG_WRITE, False),
        (Role.ADMIN, Permission.CONFIG_WRITE, True),
        (Role.ADMIN, Permission.TENANTS_CREATE, False),
        (Role.OPERATOR, Permission.TENANTS_CREATE, True),
    ],
)
def test_role_table(role, permission, allowed):
    assert (permission in ROLE_PERMISSIONS[role]) is allowed


def test_only_the_operator_crosses_tenants():
    mine, other = uuid.uuid4(), uuid.uuid4()
    assert can_access_tenant(Role.ADMIN, mine, mine)
    assert not can_access_tenant(Role.ADMIN, mine, other)
    assert not can_access_tenant(Role.ADMIN, None, other)
    assert can_access_tenant(Role.OPERATOR, None, other)


def test_admin_token_round_trip():
    tenant = uuid.uuid4()
    token, _ = issue_admin_token(
        role=Role.AGENT, tenant_id=tenant, name="Test", signing_key=KEY, ttl=timedelta(hours=1)
    )
    session = verify_admin_token(token, KEY)
    assert (session.role, session.tenant_id, session.name) == (Role.AGENT, tenant, "Test")


def test_expired_and_forged_admin_tokens_are_refused():
    expired, _ = issue_admin_token(
        role=Role.ADMIN, tenant_id=None, name="Test", signing_key=KEY, ttl=timedelta(seconds=-5)
    )
    with pytest.raises(AdminSessionError) as expired_error:
        verify_admin_token(expired, KEY)
    assert expired_error.value.code == "session_expired"
    valid, _ = issue_admin_token(
        role=Role.ADMIN, tenant_id=None, name="Test", signing_key=KEY, ttl=timedelta(hours=1)
    )
    with pytest.raises(AdminSessionError):
        verify_admin_token(valid, "z" * 40)


def test_a_chat_session_is_not_an_admin_session_and_the_other_way_round():
    chat_token, _ = issue_session_token(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        customer_id=None,
        level=IdentityLevel.ANONYMOUS,
        signing_key=KEY,
        ttl=timedelta(hours=1),
    )
    admin_token, _ = issue_admin_token(
        role=Role.OPERATOR, tenant_id=None, name="Test", signing_key=KEY, ttl=timedelta(hours=1)
    )
    with pytest.raises(AdminSessionError):
        verify_admin_token(chat_token, KEY)
    with pytest.raises(SessionError):
        verify_session_token(admin_token, KEY)

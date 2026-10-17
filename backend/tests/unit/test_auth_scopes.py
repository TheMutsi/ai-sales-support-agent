from app.auth.scopes import IdentityLevel, Scope, scopes_for


def test_anonymous_can_only_read_the_knowledge_base():
    assert scopes_for(IdentityLevel.ANONYMOUS) == {Scope.KB_READ}


def test_store_login_and_otp_login_share_the_same_scopes():
    """Both prove the same thing — who the customer is — so they unlock the same
    actions; only *how* identity was established differs."""
    assert scopes_for(IdentityLevel.STORE_LOGIN) == scopes_for(IdentityLevel.OTP_LOGIN)


def test_verified_customers_can_act_on_their_account():
    scopes = scopes_for(IdentityLevel.STORE_LOGIN)

    assert {Scope.CUSTOMER_READ, Scope.TICKET_CREATE, Scope.REFUND_REQUEST} <= scopes


def test_a_verified_customer_can_read_their_own_orders():
    assert Scope.ORDER_READ in scopes_for(IdentityLevel.OTP_LOGIN)


def test_order_lookup_is_read_only_and_exposes_no_personal_data():
    scopes = scopes_for(IdentityLevel.ORDER_LOOKUP)

    assert scopes == {Scope.KB_READ, Scope.ORDER_READ}
    assert Scope.CUSTOMER_READ not in scopes


def test_tenant_overrides_replace_a_levels_defaults():
    overrides = {"order_lookup": ["kb:read"]}

    assert scopes_for(IdentityLevel.ORDER_LOOKUP, overrides) == {Scope.KB_READ}
    # Levels the tenant didn't override keep the defaults.
    assert scopes_for(IdentityLevel.ANONYMOUS, overrides) == {Scope.KB_READ}


def test_unknown_scope_in_an_override_is_ignored_not_granted():
    """A typo in backoffice config must never widen access."""
    overrides = {"anonymous": ["kb:read", "root:everything"]}

    assert scopes_for(IdentityLevel.ANONYMOUS, overrides) == {Scope.KB_READ}


def test_a_level_without_a_customer_cannot_be_given_customer_scopes_by_an_override():
    """Found in review: such a scope would send a visitor with no customer into a node that
    needs one, which fails with a 500 instead of asking them to identify. Closed in the
    scopes themselves, since an override is configuration and must never widen access."""
    everything = [scope.value for scope in Scope]

    for level in (IdentityLevel.ORDER_LOOKUP, IdentityLevel.ANONYMOUS):
        granted = scopes_for(level, {level.value: everything})
        assert granted == {Scope.KB_READ, Scope.ORDER_READ}

    # Levels that do have a customer keep what the tenant gives them.
    assert Scope.CUSTOMER_READ in scopes_for(IdentityLevel.OTP_LOGIN, {"otp_login": everything})


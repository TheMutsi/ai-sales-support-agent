from app.agent.permissions import REQUIRED_SCOPE, identity_methods_for
from app.auth.scopes import Scope
from app.schemas.agent import Intent


def test_questions_the_knowledge_base_answers_need_no_identity():
    for intent in (
        Intent.PRODUCT_QUESTION,
        Intent.PRICING_QUESTION,
        Intent.TECHNICAL_SUPPORT,
        Intent.SMALL_TALK,
    ):
        assert REQUIRED_SCOPE[intent] == Scope.KB_READ


def test_anything_about_the_customers_own_account_needs_a_scope_an_anonymous_visitor_lacks():
    for intent, scope in {
        Intent.BILLING_QUESTION: Scope.CUSTOMER_READ,
        Intent.UPGRADE_REQUEST: Scope.CUSTOMER_READ,
        Intent.REFUND_REQUEST: Scope.REFUND_REQUEST,
        Intent.HUMAN_ESCALATION: Scope.TICKET_CREATE,
    }.items():
        assert REQUIRED_SCOPE[intent] == scope


def test_every_intent_is_covered_except_unsupported_which_is_handled_by_routing():
    assert set(Intent) - set(REQUIRED_SCOPE) == {Intent.UNSUPPORTED}


def test_account_data_is_unlocked_by_a_one_time_code():
    assert identity_methods_for(Scope.CUSTOMER_READ, None) == ["otp"]
    assert identity_methods_for(Scope.REFUND_REQUEST, None) == ["otp"]


def test_reading_an_order_is_also_unlocked_by_the_order_id():
    assert identity_methods_for(Scope.ORDER_READ, None) == ["otp", "order_id"]


def test_a_tenant_can_take_a_method_away_by_removing_the_scope_from_its_level():
    overrides = {"otp_login": ["kb:read"]}

    assert identity_methods_for(Scope.ORDER_READ, overrides) == ["order_id"]
    assert identity_methods_for(Scope.CUSTOMER_READ, overrides) == []


def test_the_shops_own_login_is_never_offered_in_the_chat():
    """store_login happens on the shop's page, not in a form the widget can show."""
    assert "store_login" not in identity_methods_for(Scope.CUSTOMER_READ, None)


def test_asking_about_an_order_needs_the_scope_to_read_one():
    assert REQUIRED_SCOPE[Intent.ORDER_STATUS] == Scope.ORDER_READ
    assert REQUIRED_SCOPE[Intent.ORDER_RETURN] == Scope.REFUND_REQUEST


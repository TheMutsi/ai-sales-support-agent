"""Unit tests for the response_writer node: `_build_context_blob` (a pure
function, tested directly) and `response_writer_node` (LLM mocked out, same
pattern as `test_agent_nodes_intent_router.py`)."""

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import response_writer as response_writer_module
from app.schemas.agent import Intent
from app.schemas.tools import PlanSummary, TicketReceipt


class _FakeChatModel:
    """Mimics only the chain `response_writer_node` calls: `.with_retry(...)`
    returns self, `.invoke(...)` hands back a fixed `AIMessage`."""

    def __init__(self, response: AIMessage):
        self._response = response
        self.bound_tools: list | None = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages):
        return self._response


def test_context_blob_is_empty_note_when_state_has_no_extra_data():
    blob = response_writer_module._build_context_blob({})
    assert blob == "No additional data was retrieved for this request."


def test_context_blob_includes_populated_fields_only():
    ticket = TicketReceipt(ticket_id=uuid.uuid4(), status="open", created_at="2026-01-01T00:00:00")
    state = {"ticket_receipt": ticket}

    blob = response_writer_module._build_context_blob(state)

    assert "Support ticket created" in blob
    assert "Customer account" not in blob


def test_context_blob_lists_plan_prices_in_dollars():
    catalog = [
        PlanSummary(
            slug="enterprise",
            name="Enterprise",
            price_cents=49900,
            billing_period="monthly",
            seat_limit=None,
            api_call_limit=None,
            features=["sso"],
        )
    ]

    blob = response_writer_module._build_context_blob({"plan_catalog": catalog})

    assert "Plan catalog (list prices)" in blob
    assert "Enterprise: $499.00, billed monthly; seats: unlimited" in blob


def test_node_returns_the_llms_message_appended_to_state(monkeypatch):
    fake_reply = AIMessage(content="Claro, te cuento...")
    monkeypatch.setattr(
        response_writer_module, "get_chat_model", lambda: _FakeChatModel(fake_reply)
    )

    state = {"messages": [HumanMessage(content="que reportes puedo generar?")]}
    result = response_writer_module.response_writer_node(state)

    assert result == {"messages": [fake_reply]}


@pytest.mark.parametrize(
    "intent",
    [
        Intent.PRODUCT_QUESTION,
        Intent.PRICING_QUESTION,
        Intent.TECHNICAL_SUPPORT,
        Intent.BILLING_QUESTION,
    ],
)
def test_binds_the_knowledge_base_tool_for_rag_eligible_intents(monkeypatch, intent):
    fake_reply = AIMessage(content="It's $49/month.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda customer_id: "fake-tool"
    )

    state = {
        "customer_id": "c-1",
        "intent": intent,
        "messages": [HumanMessage(content="how much is the pro plan?")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools == ["fake-tool"]


def test_does_not_bind_a_tool_for_non_rag_intents(monkeypatch):
    fake_reply = AIMessage(content="A ticket has been created.")
    fake_model = _FakeChatModel(fake_reply)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: fake_model)

    state = {
        "customer_id": "c-1",
        "intent": Intent.REFUND_REQUEST,
        "messages": [HumanMessage(content="I want my money back.")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools is None


class _ScriptedChatModel(_FakeChatModel):
    """Returns the scripted replies in order and records each prompt."""

    def __init__(self, *responses: AIMessage):
        super().__init__(responses[0])
        self._responses = list(responses)
        self.prompts: list[list] = []

    def invoke(self, messages):
        self.prompts.append(messages)
        return self._responses[len(self.prompts) - 1]


def _search_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "search_knowledge_base_tool", "args": {"query": "sso"}, "id": "1"}],
    )


def _run_writer(monkeypatch, model, intent, tool_call_rounds=0) -> dict:
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda customer_id: "fake-tool"
    )
    state = {
        "customer_id": "c-1",
        "intent": intent,
        "tool_call_rounds": tool_call_rounds,
        "messages": [HumanMessage(content="How do I set up SSO?")],
    }
    return response_writer_module.response_writer_node(state)


def test_retries_once_with_a_reminder_when_a_kb_intent_skips_the_search(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content=""), _search_call())

    result = _run_writer(monkeypatch, model, Intent.TECHNICAL_SUPPORT)

    assert result["messages"][0].tool_calls
    assert len(model.prompts) == 2
    assert "Call the search tool now" in model.prompts[1][0].content


def test_keeps_the_retry_reply_even_if_it_still_does_not_search(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content=""), AIMessage(content="No info."))

    result = _run_writer(monkeypatch, model, Intent.PRODUCT_QUESTION)

    assert result["messages"][0].content == "No info."
    assert len(model.prompts) == 2


@pytest.mark.parametrize(
    ("intent", "tool_call_rounds"),
    [
        (Intent.BILLING_QUESTION, 0),  # answerable from customer context
        (Intent.PRICING_QUESTION, 0),  # arrives with the plan catalog
        (Intent.TECHNICAL_SUPPORT, 1),  # already searched this turn
    ],
)
def test_does_not_retry_when_a_search_is_not_required(monkeypatch, intent, tool_call_rounds):
    model = _ScriptedChatModel(AIMessage(content="Here is the answer."))

    _run_writer(monkeypatch, model, intent, tool_call_rounds)

    assert len(model.prompts) == 1


def _returning(outcome, order_status="open", cents=6999, **extra) -> dict:
    from datetime import UTC, datetime

    from app.schemas.orders import OrderDetails, ReturnResult

    order = OrderDetails(
        order_id="A" * 20, customer_email="mail2@gmail.com", plan_slug="starter", amount_cents=cents,
        currency="usd", status=order_status, created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    return {"return_result": ReturnResult(outcome=outcome, order=order, **extra)}


def test_the_writer_is_given_the_offer_with_its_numbers_worked_out_and_told_nothing_was_done():
    from app.schemas.orders import RetentionOffer, ReturnOutcome

    blob = response_writer_module._build_context_blob(
        _returning(ReturnOutcome.OFFER, offer=RetentionOffer(refund_cents=1400, credit_points=2100))
    )

    assert "$14.00 back to their card" in blob and "2,100 points" in blob
    assert "Nothing has been done yet" in blob and "cancelled" not in blob.replace("cannot", "")


def test_an_offer_for_an_order_on_its_way_says_it_cannot_be_rejected_now():
    from app.schemas.orders import RetentionOffer, ReturnOutcome

    blob = response_writer_module._build_context_blob(
        _returning(
            ReturnOutcome.OFFER, order_status="in_delivery",
            offer=RetentionOffer(refund_cents=1400, credit_points=2100),
        )
    )

    assert "cannot be rejected now" in blob and "once it arrives" in blob


def test_what_was_done_is_stated_as_done_and_what_was_not_is_not():
    from app.schemas.orders import RetentionChoice, RetentionReceipt, ReturnOutcome

    receipt = RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.CREDITS, credit_points=2100)

    kept = response_writer_module._build_context_blob(_returning(ReturnOutcome.KEPT_WITH_CREDITS, receipt=receipt))
    cancelled = response_writer_module._build_context_blob(_returning(ReturnOutcome.CANCELLED, cents=2999))
    confirm = response_writer_module._build_context_blob(_returning(ReturnOutcome.CONFIRM_CANCEL, cents=2999))

    assert "2,100 points added to their account" in kept and "ALREADY BEEN DONE" in kept
    assert "HAS BEEN cancelled" in cancelled
    assert "Nothing has been done yet" in confirm and "HAS BEEN" not in confirm


def test_an_order_kept_with_the_offer_says_so_in_the_listing():
    from datetime import UTC, datetime

    from app.schemas.orders import OrderDetails, RetentionChoice, RetentionReceipt

    order = OrderDetails(
        order_id="A" * 20, customer_email="a@b.test", plan_slug="starter", amount_cents=6999,
        currency="usd", status="open", created_at=datetime(2026, 10, 1, tzinfo=UTC),
        retention=RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.REFUND, refund_cents=1400),
    )

    blob = response_writer_module._build_context_blob({"intent": "order_status", "customer_orders": [order]})

    assert "kept by the customer with a refund of $14.00 to their card" in blob


def test_every_other_outcome_tells_the_writer_what_to_say_and_that_nothing_extra_was_done():
    from app.schemas.orders import ReturnOutcome

    expected = {
        ReturnOutcome.NOTHING_TO_RETURN: "do not ask for an order number",
        ReturnOutcome.RETURN_LATER: "once it arrives",
        ReturnOutcome.KEPT_AS_IS: "Nothing was changed",
        ReturnOutcome.NOT_AVAILABLE: "nothing was changed",
        ReturnOutcome.CHOOSE_ORDER: "Ask which of these orders",
    }
    for outcome, text in expected.items():
        assert text in response_writer_module._build_context_blob(_returning(outcome))


def test_the_offer_lists_the_free_next_order_and_taking_it_gives_the_coupon():
    from app.schemas.orders import RetentionChoice, RetentionOffer, RetentionReceipt, ReturnOutcome

    offer = response_writer_module._build_context_blob(
        _returning(ReturnOutcome.OFFER, offer=RetentionOffer(refund_cents=1400, credit_points=2100))
    )
    receipt = RetentionReceipt(order_id="A" * 20, choice=RetentionChoice.NEXT_ORDER_FREE, coupon_code="FREE-AAAAAA")
    kept = response_writer_module._build_context_blob(_returning(ReturnOutcome.KEPT_WITH_FREE_ORDER, receipt=receipt))

    assert "(3) their next order free" in offer
    assert "their next order free (coupon FREE-AAAAAA)" in kept and "ALREADY BEEN DONE" in kept

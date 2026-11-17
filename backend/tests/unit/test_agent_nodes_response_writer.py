import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import response_writer as response_writer_module
from app.agent.prompts.response_writer import RESPONSE_WRITER_SYSTEM_PROMPT
from app.schemas.agent import Intent
from app.schemas.rag import DocumentMapEntry
from app.schemas.tools import EscalationReceipt, PlanSummary

TENANT_ID = uuid.uuid4()
DOCUMENT_ID = uuid.uuid4()


def _stub_tools(monkeypatch, entries=()):
    monkeypatch.setattr(
        response_writer_module, "make_search_knowledge_base_tool", lambda *a: "fake-search"
    )
    monkeypatch.setattr(response_writer_module, "make_open_documents_tool", lambda *a: "fake-open")
    monkeypatch.setattr(response_writer_module, "resolve_plan_slug", lambda state: "pro")
    monkeypatch.setattr(
        response_writer_module, "get_document_map", lambda tenant_id, plan_slug: entries
    )


class _FakeChatModel:
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
    receipt = EscalationReceipt(reference="MF-ABCD2345", route="live", reason="agent_available", category="escalation")
    state = {"escalation_receipt": receipt}

    blob = response_writer_module._build_context_blob(state)

    assert "Follow-up number: MF-ABCD2345" in blob
    assert "agent will join" in blob
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
    _stub_tools(monkeypatch)

    state = {
        "customer_id": "c-1",
        "tenant_id": str(TENANT_ID),
        "intent": intent,
        "messages": [HumanMessage(content="how much is the pro plan?")],
    }
    response_writer_module.response_writer_node(state)

    assert fake_model.bound_tools == ["fake-search", "fake-open"]


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
    _stub_tools(monkeypatch)
    state = {
        "customer_id": "c-1",
        "tenant_id": str(TENANT_ID),
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
        (Intent.BILLING_QUESTION, 0),
        (Intent.PRICING_QUESTION, 0),
        (Intent.TECHNICAL_SUPPORT, 1),
    ],
)
def test_does_not_retry_when_a_search_is_not_required(monkeypatch, intent, tool_call_rounds):
    model = _ScriptedChatModel(AIMessage(content="Here is the answer."))

    _run_writer(monkeypatch, model, intent, tool_call_rounds)

    assert len(model.prompts) == 1


def test_an_order_kept_with_the_offer_says_so_in_the_listing():
    from datetime import UTC, datetime

    from app.schemas.orders import OrderDetails, RetentionChoice, RetentionReceipt

    order = OrderDetails(
        order_id="A" * 20,
        customer_email="a@b.test",
        plan_slug="starter",
        amount_cents=6999,
        currency="usd",
        status="open",
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        retention=RetentionReceipt(
            order_id="A" * 20, choice=RetentionChoice.REFUND, refund_cents=1400
        ),
    )

    blob = response_writer_module._build_context_blob(
        {"intent": "order_status", "customer_orders": [order]}
    )

    assert "kept by the customer with a refund of $14.00 to their card" in blob


def test_context_blob_hides_the_internal_customer_id():
    from app.schemas.tools import CustomerContext

    customer_id = uuid.uuid4()
    context = CustomerContext(
        customer_id=customer_id,
        name="Ada",
        email="ada@example.com",
        company=None,
        status="active",
        subscription=None,
    )

    blob = response_writer_module._build_context_blob({"customer_context": context})

    assert "Ada" in blob
    assert str(customer_id) not in blob


def test_context_blob_hides_the_customer_email():
    from app.schemas.tools import CustomerContext

    context = CustomerContext(
        customer_id=uuid.uuid4(),
        name="Ada",
        email="ada@example.com",
        company=None,
        status="active",
        subscription=None,
    )
    blob = response_writer_module._build_context_blob({"customer_context": context})
    assert "ada@example.com" not in blob


def _terms_entry() -> DocumentMapEntry:
    return DocumentMapEntry(
        document_id=DOCUMENT_ID,
        title="Terms and Conditions",
        when_to_use="Contract questions",
        estimated_tokens=900,
    )


def test_the_document_map_follows_the_instructions_and_the_context(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content="ok"))
    _stub_tools(monkeypatch, (_terms_entry(),))
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)

    response_writer_module.response_writer_node(
        {
            "customer_id": None,
            "tenant_id": str(TENANT_ID),
            "intent": Intent.PRICING_QUESTION,
            "messages": [HumanMessage(content="terms?")],
        }
    )

    prompt = model.prompts[0][0].content
    assert prompt.split("\n\n")[0] == RESPONSE_WRITER_SYSTEM_PROMPT.split("\n\n")[0]
    assert prompt.index("Context:") < prompt.index("<document_map>")
    assert f"- id: {DOCUMENT_ID} | title: Terms and Conditions | when to use: Contract questions | ~900 tokens" in prompt


def test_no_document_map_block_when_the_tenant_has_no_documents(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content="ok"))
    _stub_tools(monkeypatch)
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)

    response_writer_module.response_writer_node(
        {
            "customer_id": None,
            "tenant_id": str(TENANT_ID),
            "intent": Intent.PRICING_QUESTION,
            "messages": [HumanMessage(content="terms?")],
        }
    )

    assert "<document_map>" not in model.prompts[0][0].content


def test_no_document_map_for_intents_without_the_knowledge_base(monkeypatch):
    model = _ScriptedChatModel(AIMessage(content="ok"))
    _stub_tools(monkeypatch, (_terms_entry(),))
    monkeypatch.setattr(response_writer_module, "get_chat_model", lambda: model)

    response_writer_module.response_writer_node(
        {"customer_id": None, "intent": Intent.REFUND_REQUEST, "messages": [HumanMessage(content="refund")]}
    )

    assert "<document_map>" not in model.prompts[0][0].content


def test_the_retry_accepts_an_open_documents_call_as_the_first_tool_use(monkeypatch):
    open_call = AIMessage(
        content="",
        tool_calls=[{"name": "open_documents_tool", "args": {"document_ids": []}, "id": "1"}],
    )
    model = _ScriptedChatModel(open_call)

    result = _run_writer(monkeypatch, model, Intent.PRODUCT_QUESTION)

    assert result["messages"][0] is open_call
    assert len(model.prompts) == 1

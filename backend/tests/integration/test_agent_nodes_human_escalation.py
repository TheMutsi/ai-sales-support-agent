"""Integration test for the human_escalation node — needs a real DB because
`create_support_ticket` persists a row, and a mocked LLM for the subject/
description draft (same reasoning as the other agent-node LLM tests: don't
depend on real model output for a deterministic-control-flow test)."""

from sqlalchemy.orm import Session

from app.agent.nodes import human_escalation as human_escalation_module
from app.db.models import Ticket
from app.schemas.agent import Intent, TicketDraft
from tests.integration.conftest import customer_by_email


class _FakeStructuredChatModel:
    def __init__(self, response: TicketDraft):
        self._response = response

    def with_structured_output(self, schema):
        return self

    def with_retry(self, **kwargs):
        return self

    def invoke(self, messages):
        return self._response


def test_creates_a_ticket_with_the_llms_draft_and_the_mapped_category(
    seeded_db: Session, monkeypatch
):
    fake_draft = TicketDraft(
        subject="Refund request for last month",
        description="Customer wants a refund, says they didn't use the service.",
    )
    monkeypatch.setattr(
        human_escalation_module,
        "get_chat_model",
        lambda: _FakeStructuredChatModel(fake_draft),
    )
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")

    state = {"customer_id": customer.id, "intent": Intent.REFUND_REQUEST, "messages": []}
    result = human_escalation_module.human_escalation_node(state)

    assert result["escalated"] is True
    stored = seeded_db.get(Ticket, result["ticket_receipt"].ticket_id)
    assert stored.category == "refund"
    assert stored.subject == fake_draft.subject
    assert stored.description == fake_draft.description


def test_defaults_to_other_category_for_an_unmapped_intent(seeded_db: Session, monkeypatch):
    fake_draft = TicketDraft(subject="Unclear request", description="Couldn't classify.")
    monkeypatch.setattr(
        human_escalation_module,
        "get_chat_model",
        lambda: _FakeStructuredChatModel(fake_draft),
    )
    customer = customer_by_email(seeded_db, "ava.chen@northlightstudio.com")

    state = {"customer_id": customer.id, "intent": Intent.UNSUPPORTED, "messages": []}
    result = human_escalation_module.human_escalation_node(state)

    stored = seeded_db.get(Ticket, result["ticket_receipt"].ticket_id)
    assert stored.category == "other"

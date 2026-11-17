import uuid
from datetime import UTC, datetime

import pytest

from app.agent.llm_tools import documents as documents_module
from app.agent.llm_tools import plan_scope as plan_scope_module
from app.schemas.rag import DocType, OpenDocumentsResult, OpenedDocument, SourceReference
from app.schemas.tools import CustomerContext, PlanSummary, SubscriptionSummary

TENANT_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("the agent layer must not reach the database")

    monkeypatch.setattr(plan_scope_module, "current_plan_slug", fail)


def _opened(title, **overrides) -> OpenedDocument:
    fields = {
        "document_id": uuid.uuid4(),
        "title": title,
        "doc_type": DocType.POLICY,
        "source": f"{title}.md",
        "version": 3,
        "estimated_tokens": 10,
        "text": f"{title} text",
    }
    return OpenedDocument(**{**fields, **overrides})


def test_the_wrapper_builds_sources_from_the_tool_result_without_the_database(monkeypatch):
    opened = _opened("Terms")
    omitted = _opened("Long", text=None, omitted_reason="document_too_long")
    monkeypatch.setattr(
        documents_module,
        "open_documents",
        lambda tenant_id, plan_slug, ids: OpenDocumentsResult(documents=[opened, omitted]),
    )
    tool = documents_module.make_open_documents_tool(TENANT_ID, "pro")

    content, sources = tool.func([opened.document_id, omitted.document_id])

    assert sources == [SourceReference(title="Terms", doc_type=DocType.POLICY, source="Terms.md", version=3)]
    assert "Terms text" in content


def test_the_wrapper_passes_the_bound_plan_to_the_documents_tool(monkeypatch):
    seen = []
    monkeypatch.setattr(
        documents_module,
        "open_documents",
        lambda tenant_id, plan_slug, ids: seen.append((tenant_id, plan_slug)) or OpenDocumentsResult(),
    )
    tool = documents_module.make_open_documents_tool(TENANT_ID, "starter")

    tool.func([uuid.uuid4()])

    assert seen == [(TENANT_ID, "starter")]


def _context(plan_slug: str | None) -> CustomerContext:
    subscription = None
    if plan_slug is not None:
        plan = PlanSummary(
            slug=plan_slug,
            name=plan_slug.title(),
            price_cents=100,
            billing_period="monthly",
            seat_limit=None,
            api_call_limit=None,
            features=[],
        )
        subscription = SubscriptionSummary(
            status="active", current_period_end=datetime(2030, 1, 1, tzinfo=UTC), canceled_at=None, plan=plan
        )
    return CustomerContext(
        customer_id=uuid.uuid4(), name="Ada", email="a@x.io", company=None, status="active", subscription=subscription
    )


def test_the_plan_slug_is_none_for_an_anonymous_visitor():
    assert plan_scope_module.resolve_plan_slug({"customer_id": None}) is None


def test_the_plan_slug_already_resolved_this_turn_is_reused():
    state = {"customer_id": str(uuid.uuid4()), "knowledge_plan_slug": "pro"}

    assert plan_scope_module.resolve_plan_slug(state) == "pro"


def test_a_loaded_customer_context_gives_the_plan_slug_without_a_lookup():
    state = {"customer_id": str(uuid.uuid4()), "customer_context": _context("pro")}

    assert plan_scope_module.resolve_plan_slug(state) == "pro"


def test_a_loaded_customer_context_without_a_subscription_has_no_plan():
    state = {"customer_id": str(uuid.uuid4()), "customer_context": _context(None)}

    assert plan_scope_module.resolve_plan_slug(state) is None


def test_otherwise_the_plan_is_looked_up_once_in_the_tools_layer(monkeypatch):
    customer_id = uuid.uuid4()
    monkeypatch.setattr(plan_scope_module, "current_plan_slug", lambda given: "starter" if given == customer_id else None)

    assert plan_scope_module.resolve_plan_slug({"customer_id": str(customer_id)}) == "starter"

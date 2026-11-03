"""Properties and tags on a conversation: public hints, set by the session's own visitor."""

import pytest
from fastapi.testclient import TestClient

from app.auth.credentials import generate_api_key
from app.db.models import Tenant
from app.db.session import SessionLocal
from app.main import app

client = TestClient(app)


@pytest.fixture
def conversation(tenant_wipe):
    with SessionLocal() as db:
        tenant = Tenant(name="Shop", api_key=generate_api_key())
        db.add(tenant)
        db.commit()
        api_key = tenant.api_key
    body = client.post("/api/conversations", json={"api_key": api_key}).json()
    return {
        "id": body["conversation_id"],
        "headers": {"Authorization": f"Bearer {body['session_token']}"},
    }


def _update(conversation, **body):
    return client.post(
        f"/api/conversations/{conversation['id']}/context",
        json=body,
        headers=conversation["headers"],
    )


def test_properties_and_tags_are_stored_and_merged(conversation):
    first = _update(conversation, properties={"device": "iphone"}, add_tags=["landing-sale"])
    assert first.status_code == 200
    second = _update(conversation, properties={"plan": "club"}, add_tags=["landing-sale", "vip"])
    assert second.json() == {
        "properties": {"device": "iphone", "plan": "club"},
        "tags": ["landing-sale", "vip"],
    }


def test_null_removes_a_property_and_remove_tags_removes_a_tag(conversation):
    _update(conversation, properties={"device": "iphone"}, add_tags=["a", "b"])
    result = _update(conversation, properties={"device": None}, remove_tags=["a"])
    assert result.json() == {"properties": {}, "tags": ["b"]}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"properties": {"Bad Key": "x"}}, "invalid_property_key"),
        ({"properties": {"device": "x" * 101}}, "invalid_property_value"),
        ({"properties": {"device": "a\nb"}}, "invalid_property_value"),
        ({"add_tags": ["Has Space"]}, "invalid_tag"),
        ({"properties": {f"k{i}": "v" for i in range(21)}}, None),
    ],
)
def test_invalid_updates_are_refused(conversation, body, code):
    response = _update(conversation, **body)
    assert response.status_code == 422
    if code:
        assert response.json()["detail"]["code"] == code


def test_too_many_tags_across_updates_is_refused_and_changes_nothing(conversation):
    _update(conversation, add_tags=[f"t{i}" for i in range(20)])
    response = _update(conversation, add_tags=["one-more"])
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "too_many_tags"
    assert _update(conversation).json()["tags"] == [f"t{i}" for i in range(20)]


def test_another_conversation_is_a_404(conversation):
    response = client.post(
        "/api/conversations/00000000-0000-0000-0000-000000000000/context",
        json={"add_tags": ["x"]},
        headers=conversation["headers"],
    )
    assert response.status_code == 404


def test_it_needs_a_session(conversation):
    response = client.post(f"/api/conversations/{conversation['id']}/context", json={})
    assert response.status_code == 401

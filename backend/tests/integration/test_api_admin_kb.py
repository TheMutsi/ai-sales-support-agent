import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin import ADMIN_ROUTERS
from app.api.admin_kb import get_embedder
from app.auth.credentials import generate_api_key
from app.db.models import DocumentChunk, Plan, Tenant
from app.db.session import SessionLocal
from app.rag import catalog
from app.rag.tokens import DOCUMENT_TOKEN_LIMIT

app = FastAPI()
for router in ADMIN_ROUTERS:
    app.include_router(router, prefix="/api")
client = TestClient(app)


class FakeEmbedder:
    def embed_documents(self, texts):
        return [[0.1] * 768 for _ in texts]


class BrokenEmbedder:
    def embed_documents(self, texts):
        raise RuntimeError("embedding service is down")


@pytest.fixture(autouse=True)
def working_embedder():
    app.dependency_overrides[get_embedder] = FakeEmbedder
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def tenants(tenant_wipe):
    with SessionLocal() as db:
        a, b = Tenant(name="Shop A", api_key=generate_api_key()), Tenant(name="Shop B", api_key=generate_api_key())
        db.add_all([a, b])
        db.commit()
        yield {"a": a.id, "b": b.id}


@pytest.fixture
def pro_plan(tenants):
    with SessionLocal() as db:
        existing = db.query(Plan).filter_by(slug="pro").one_or_none()
        if existing is None:
            db.add(Plan(slug="pro", name="Pro", price_cents=2900, billing_period="monthly", seat_limit=None, api_call_limit=None))
            db.commit()


def _login(role, tenant_id=None, name="Lucia"):
    body = client.post(
        "/api/admin/session", json={"role": role, "tenant_id": str(tenant_id) if tenant_id else None, "name": name}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


def _base(tenant_id) -> str:
    return f"/api/admin/tenants/{tenant_id}/kb/documents"


def _new_document(tenants, content="# Plans\n\nThe Pro plan costs 29 dollars.") -> dict:
    response = client.post(
        _base(tenants["a"]),
        json={
            "title": "Plans",
            "doc_type": "billing",
            "plan_scope": None,
            "when_to_use": "plan questions",
            "content": content,
        },
        headers=_login("admin", tenants["a"]),
    )
    assert response.status_code == 201
    return response.json()


def _publish(tenants, document_id):
    return client.post(
        f"{_base(tenants['a'])}/{document_id}/draft/publish", headers=_login("admin", tenants["a"])
    )


def _save_draft(tenants, document_id, content):
    return client.put(
        f"{_base(tenants['a'])}/{document_id}/draft", json={"content": content}, headers=_login("admin", tenants["a"])
    )


def test_creating_a_document_makes_draft_version_one_that_serves_nothing(tenants):
    document = _new_document(tenants)
    assert document["published_version"] is None
    assert document["has_draft"] is True
    assert [(v["version"], v["status"]) for v in document["versions"]] == [(1, "draft")]
    assert document["fits_whole_document"] is True


def test_a_viewer_reads_but_cannot_write(tenants):
    document = _new_document(tenants)
    viewer = _login("viewer", tenants["a"])
    assert client.get(_base(tenants["a"]), headers=viewer).status_code == 200
    assert client.get(f"{_base(tenants['a'])}/{document['id']}", headers=viewer).status_code == 200
    write_calls = [
        client.post(_base(tenants["a"]), json={"title": "x", "doc_type": "faq", "content": "x"}, headers=viewer),
        client.put(f"{_base(tenants['a'])}/{document['id']}/draft", json={"content": "x"}, headers=viewer),
        client.post(f"{_base(tenants['a'])}/{document['id']}/draft/publish", headers=viewer),
        client.post(f"{_base(tenants['a'])}/{document['id']}/archive", headers=viewer),
    ]
    assert [call.status_code for call in write_calls] == [403, 403, 403, 403]


def test_another_tenant_is_refused_and_cannot_see_the_document(tenants):
    document = _new_document(tenants)
    other = _login("admin", tenants["b"])
    assert client.get(_base(tenants["a"]), headers=other).status_code == 403
    assert client.get(f"{_base(tenants['b'])}/{document['id']}", headers=other).status_code == 404
    assert client.get(_base(tenants["b"]), headers=other).json() == []


def test_publishing_the_draft_serves_it_and_embeds_its_chunks(tenants):
    document = _new_document(tenants)
    response = _publish(tenants, document["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["published_version"] == 1
    assert body["has_draft"] is False
    assert body["versions"][0]["status"] == "published"
    assert body["versions"][0]["published_by"] == "Lucia"
    with SessionLocal() as db:
        assert db.query(DocumentChunk).count() > 0


def test_publishing_a_second_version_archives_the_first(tenants):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nThe Pro plan costs 39 dollars.")
    body = _publish(tenants, document["id"]).json()
    assert body["published_version"] == 2
    assert [(v["version"], v["status"]) for v in body["versions"]] == [(2, "published"), (1, "archived")]


def test_saving_a_draft_replaces_the_single_draft(tenants):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    first = _save_draft(tenants, document["id"], "first edit").json()
    second = _save_draft(tenants, document["id"], "second edit").json()
    drafts = [v for v in second["versions"] if v["status"] == "draft"]
    assert [d["content"] for d in drafts] == ["second edit"]
    assert first["has_draft"] and second["has_draft"]


def test_publishing_without_a_draft_is_a_404(tenants):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    assert _publish(tenants, document["id"]).status_code == 404


def test_rolling_back_republishes_an_archived_version(tenants):
    document = _new_document(tenants, content="# Plans\n\nold text")
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nnew text")
    _publish(tenants, document["id"])
    admin = _login("admin", tenants["a"])
    first = next(v for v in client.get(f"{_base(tenants['a'])}/{document['id']}", headers=admin).json()["versions"] if v["version"] == 1)
    response = client.post(f"{_base(tenants['a'])}/{document['id']}/versions/{first['id']}/publish", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["published_version"] == 1
    assert [(v["version"], v["status"]) for v in body["versions"]] == [(2, "archived"), (1, "published")]


def test_only_an_archived_version_can_be_rolled_back_to(tenants):
    document = _new_document(tenants)
    published = _publish(tenants, document["id"]).json()
    admin = _login("admin", tenants["a"])
    version_id = published["versions"][0]["id"]
    response = client.post(f"{_base(tenants['a'])}/{document['id']}/versions/{version_id}/publish", headers=admin)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "version_not_archived"


def test_an_unknown_version_is_a_404(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    unknown = "00000000-0000-0000-0000-000000000001"
    response = client.post(f"{_base(tenants['a'])}/{document['id']}/versions/{unknown}/publish", headers=admin)
    assert response.status_code == 404


def test_an_embedding_failure_keeps_the_previous_version_serving(tenants):
    document = _new_document(tenants, content="# Plans\n\nold text")
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nnew text")
    app.dependency_overrides[get_embedder] = BrokenEmbedder
    response = _publish(tenants, document["id"])
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "embedding_failed"
    admin = _login("admin", tenants["a"])
    body = client.get(f"{_base(tenants['a'])}/{document['id']}", headers=admin).json()
    assert body["published_version"] == 1
    assert body["has_draft"] is True
    assert {v["version"]: v["status"] for v in body["versions"]} == {1: "published", 2: "draft"}


class MismatchedEmbedder:
    def embed_documents(self, texts):
        return []


def _titles_on_the_map(tenants) -> list[str]:
    return [entry.title for entry in catalog.get_document_map(tenants["a"])]


@pytest.fixture
def warm_catalog():
    catalog.document_catalog.clear()
    yield
    catalog.document_catalog.clear()


def test_publishing_a_draft_shows_on_the_document_map_at_once(tenants, warm_catalog):
    document = _new_document(tenants)
    assert _titles_on_the_map(tenants) == []
    _publish(tenants, document["id"])
    assert _titles_on_the_map(tenants) == ["Plans"]


def test_rolling_back_shows_on_the_document_map_at_once(tenants, warm_catalog):
    document = _new_document(tenants, content="# Plans\n\nold text")
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nnew text " * 200)
    _publish(tenants, document["id"])
    before = catalog.get_document_map(tenants["a"])[0].estimated_tokens
    admin = _login("admin", tenants["a"])
    first = next(
        v
        for v in client.get(f"{_base(tenants['a'])}/{document['id']}", headers=admin).json()["versions"]
        if v["version"] == 1
    )
    client.post(f"{_base(tenants['a'])}/{document['id']}/versions/{first['id']}/publish", headers=admin)
    assert catalog.get_document_map(tenants["a"])[0].estimated_tokens < before


def test_archiving_removes_the_document_from_the_map_at_once(tenants, warm_catalog):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    assert _titles_on_the_map(tenants) == ["Plans"]
    client.post(f"{_base(tenants['a'])}/{document['id']}/archive", headers=_login("admin", tenants["a"]))
    assert _titles_on_the_map(tenants) == []


def test_an_embedding_failure_is_logged(tenants, caplog):
    document = _new_document(tenants)
    app.dependency_overrides[get_embedder] = BrokenEmbedder
    with caplog.at_level("ERROR", logger="app.api.admin_kb"):
        response = _publish(tenants, document["id"])
    assert response.status_code == 502
    assert any("embedding failed" in record.message for record in caplog.records)


def test_a_failure_that_is_not_the_embedding_is_not_reported_as_one(tenants):
    document = _new_document(tenants)
    app.dependency_overrides[get_embedder] = MismatchedEmbedder
    with pytest.raises(ValueError):
        _publish(tenants, document["id"])


def test_archiving_stops_serving_the_document(tenants):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    response = client.post(f"{_base(tenants['a'])}/{document['id']}/archive", headers=_login("admin", tenants["a"]))
    assert response.status_code == 200
    body = response.json()
    assert body["published_version"] is None
    assert body["versions"][0]["status"] == "archived"


def test_an_agent_reads_but_cannot_write(tenants):
    document = _new_document(tenants)
    agent = _login("agent", tenants["a"])
    assert client.get(_base(tenants["a"]), headers=agent).status_code == 200
    response = client.put(f"{_base(tenants['a'])}/{document['id']}/draft", json={"content": "x"}, headers=agent)
    assert response.status_code == 403


def test_another_tenants_admin_cannot_write_to_the_document(tenants):
    document = _new_document(tenants)
    other = _login("admin", tenants["b"])
    calls = [
        client.put(f"{_base(tenants['a'])}/{document['id']}/draft", json={"content": "x"}, headers=other),
        client.post(f"{_base(tenants['a'])}/{document['id']}/draft/publish", headers=other),
        client.post(f"{_base(tenants['a'])}/{document['id']}/archive", headers=other),
        client.put(f"{_base(tenants['b'])}/{document['id']}/draft", json={"content": "x"}, headers=other),
    ]
    assert [call.status_code for call in calls] == [403, 403, 403, 404]


def test_the_whole_lifecycle_create_edit_publish_rollback_archive(tenants):
    admin = _login("admin", tenants["a"])
    base = _base(tenants["a"])
    document = _new_document(tenants, content="# Plans\n\nv1 text")
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nv2 text")
    published = _publish(tenants, document["id"]).json()
    first = next(v for v in published["versions"] if v["version"] == 1)
    rolled = client.post(f"{base}/{document['id']}/versions/{first['id']}/publish", headers=admin).json()
    archived = client.post(f"{base}/{document['id']}/archive", headers=admin).json()
    assert rolled["published_version"] == 1
    assert archived["published_version"] is None
    assert {v["version"]: v["status"] for v in archived["versions"]} == {1: "archived", 2: "archived"}
    listed = client.get(base, headers=admin).json()
    assert [(i["published_version"], i["has_draft"]) for i in listed] == [(None, False)]


def test_the_list_flags_documents_too_big_to_open_whole(tenants):
    _new_document(tenants, content="x" * (DOCUMENT_TOKEN_LIMIT * 3 + 10))
    items = client.get(_base(tenants["a"]), headers=_login("viewer", tenants["a"])).json()
    assert [(i["title"], i["fits_whole_document"], i["has_draft"]) for i in items] == [("Plans", False, True)]
    assert items[0]["estimated_tokens"] > DOCUMENT_TOKEN_LIMIT


def _update_details(tenant_id, document_id, headers, **changes):
    body = {"title": "Plans", "doc_type": "billing", "plan_scope": None, "when_to_use": "plan questions", **changes}
    return client.patch(f"{_base(tenant_id)}/{document_id}", json=body, headers=headers)


def test_updating_details_changes_the_document_fields_and_keeps_its_versions(tenants, pro_plan):
    document = _new_document(tenants)
    response = _update_details(
        tenants["a"],
        document["id"],
        _login("admin", tenants["a"]),
        title="Pricing",
        doc_type="policy",
        plan_scope="pro",
        when_to_use="questions about prices",
    )
    assert response.status_code == 200
    updated = response.json()
    assert (updated["title"], updated["doc_type"], updated["plan_scope"]) == ("Pricing", "policy", "pro")
    assert updated["when_to_use"] == "questions about prices"
    assert [v["version"] for v in updated["versions"]] == [1]


def test_updating_details_is_validated_like_creating(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    assert _update_details(tenants["a"], document["id"], admin, title="").status_code == 422
    assert _update_details(tenants["a"], document["id"], admin, doc_type="nonsense").status_code == 422
    assert _update_details(tenants["a"], document["id"], admin, when_to_use="x" * 1001).status_code == 422


def test_updating_details_needs_write_permission(tenants):
    document = _new_document(tenants)
    for role in ("viewer", "agent"):
        response = _update_details(tenants["a"], document["id"], _login(role, tenants["a"]))
        assert response.status_code == 403


def test_updating_details_of_another_tenants_document_is_refused(tenants):
    document = _new_document(tenants)
    other = _login("admin", tenants["b"])
    assert _update_details(tenants["a"], document["id"], other).status_code == 403
    assert _update_details(tenants["b"], document["id"], other).status_code == 404


def test_updating_details_of_an_unknown_document_is_a_404(tenants):
    response = _update_details(
        tenants["a"], "00000000-0000-0000-0000-000000000000", _login("admin", tenants["a"])
    )
    assert response.status_code == 404


def test_updating_when_to_use_shows_on_the_document_map_at_once(tenants, warm_catalog):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    assert catalog.get_document_map(tenants["a"])[0].when_to_use == "plan questions"
    _update_details(tenants["a"], document["id"], _login("admin", tenants["a"]), when_to_use="refund questions")
    assert catalog.get_document_map(tenants["a"])[0].when_to_use == "refund questions"


def test_updating_details_refuses_an_empty_when_to_use(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    assert _update_details(tenants["a"], document["id"], admin, when_to_use="").status_code == 422


def test_updating_details_without_a_field_does_not_clear_it(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    response = client.patch(f"{_base(tenants['a'])}/{document['id']}", json={"title": "Renamed", "doc_type": "billing"}, headers=admin)
    if response.status_code == 200:
        assert response.json()["when_to_use"] == "plan questions"
    else:
        assert response.status_code == 422


def test_updating_details_refuses_a_whitespace_only_when_to_use(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    assert _update_details(tenants["a"], document["id"], admin, when_to_use="   \n ").status_code == 422


def test_updating_details_without_plan_scope_is_refused(tenants):
    document = _new_document(tenants)
    admin = _login("admin", tenants["a"])
    body = {"title": "Plans", "doc_type": "billing", "when_to_use": "plan questions"}
    assert client.patch(f"{_base(tenants['a'])}/{document['id']}", json=body, headers=admin).status_code == 422


def test_creating_a_document_refuses_a_whitespace_only_or_missing_when_to_use(tenants):
    admin = _login("admin", tenants["a"])
    base = {"title": "Plans", "doc_type": "billing", "plan_scope": None, "content": "# Plans"}
    assert client.post(_base(tenants["a"]), json={**base, "when_to_use": "  "}, headers=admin).status_code == 422
    assert client.post(_base(tenants["a"]), json=base, headers=admin).status_code == 422


def _create_with(tenants, **changes):
    body = {"title": "Plans", "doc_type": "billing", "plan_scope": None, "when_to_use": "plan questions", "content": "# P", **changes}
    return client.post(_base(tenants["a"]), json=body, headers=_login("admin", tenants["a"]))


def test_an_unknown_plan_is_refused_on_create_and_on_update(tenants):
    document = _new_document(tenants)
    created = _create_with(tenants, plan_scope="no-such-plan")
    updated = _update_details(tenants["a"], document["id"], _login("admin", tenants["a"]), plan_scope="no-such-plan")
    for response in (created, updated):
        assert response.status_code == 422
        assert response.json()["detail"] == {"code": "unknown_plan"}


def test_a_blank_plan_scope_becomes_null(tenants):
    document = _create_with(tenants, plan_scope="   ").json()
    assert document["plan_scope"] is None
    updated = _update_details(tenants["a"], document["id"], _login("admin", tenants["a"]), plan_scope="")
    assert updated.json()["plan_scope"] is None


def test_an_existing_plan_is_accepted(tenants, pro_plan):
    assert _create_with(tenants, plan_scope="pro").json()["plan_scope"] == "pro"


@pytest.mark.parametrize("field", ["title", "when_to_use"])
@pytest.mark.parametrize("value", ["first\nsecond", "first\rsecond"])
def test_a_line_break_in_title_or_when_to_use_is_refused(tenants, field, value):
    document = _new_document(tenants)
    assert _create_with(tenants, **{field: value}).status_code == 422
    assert _update_details(tenants["a"], document["id"], _login("admin", tenants["a"]), **{field: value}).status_code == 422


def test_rolling_back_leaves_chunks_only_for_the_published_version(tenants):
    document = _new_document(tenants, content="# Plans\n\nold text")
    _publish(tenants, document["id"])
    _save_draft(tenants, document["id"], "# Plans\n\nnew text")
    _publish(tenants, document["id"])
    versions = {v["version"]: v["id"] for v in client.get(
        f"{_base(tenants['a'])}/{document['id']}", headers=_login("admin", tenants["a"])
    ).json()["versions"]}
    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter_by(document_version_id=versions[1]).count() == 0
        assert db.query(DocumentChunk).filter_by(document_version_id=versions[2]).count() > 0
    client.post(f"{_base(tenants['a'])}/{document['id']}/versions/{versions[1]}/publish", headers=_login("admin", tenants["a"]))
    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter_by(document_version_id=versions[2]).count() == 0
        assert db.query(DocumentChunk).filter_by(document_version_id=versions[1]).count() > 0


def test_archiving_a_document_removes_its_chunks(tenants):
    document = _new_document(tenants)
    _publish(tenants, document["id"])
    client.post(f"{_base(tenants['a'])}/{document['id']}/archive", headers=_login("admin", tenants["a"]))
    with SessionLocal() as db:
        assert db.query(DocumentChunk).count() == 0

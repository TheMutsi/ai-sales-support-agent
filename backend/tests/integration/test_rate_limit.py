"""Fixed-window counters in Postgres: correct across server instances, which an
in-process counter is not behind a load balancer. Applied to the endpoints a stranger
can call (starting a conversation, login, one-time codes) and to the chat per conversation."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import rate_limit as rate_limit_module
from app.api.rate_limit import client_ip, hit
from app.auth.credentials import generate_api_key
from app.auth.scopes import IdentityLevel
from app.auth.session import issue_session_token
from app.core.config import get_settings
from app.db.models import Customer, RateLimitCounter, Tenant
from app.db.session import SessionLocal
from app.main import app

NOW = datetime(2026, 10, 17, 12, 0, 30, tzinfo=UTC)  # 30 s into a minute-aligned window
client = TestClient(app)


@pytest.fixture
def db(tenant_wipe):
    with SessionLocal() as session:
        yield session


def _hit(db, key="k", limit=3, window=60, now=NOW):
    return hit(db, key=key, limit=limit, window_seconds=window, now=now)


def test_requests_up_to_the_limit_pass_and_the_next_one_says_when_to_retry(db):
    assert [_hit(db) for _ in range(3)] == [None, None, None]

    retry_after = _hit(db)

    assert retry_after == 30  # the window ends 30 s from NOW


def test_the_counter_starts_over_in_the_next_window(db):
    for _ in range(4):
        _hit(db)

    assert _hit(db, now=NOW + timedelta(seconds=31)) is None


def test_keys_are_counted_separately(db):
    for _ in range(4):
        _hit(db, key="ip:1.1.1.1")

    assert _hit(db, key="ip:2.2.2.2") is None


def test_parallel_requests_are_counted_exactly(tenant_wipe):
    """An update that reads then writes would let several slip past the limit."""

    def one(_):
        with SessionLocal() as session:
            return _hit(session, limit=5)

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(one, range(12)))

    assert results.count(None) == 5


def test_a_new_window_clears_counters_of_long_ago(db):
    _hit(db, key="old", now=NOW - timedelta(days=3))

    _hit(db, key="fresh")

    assert db.query(RateLimitCounter).filter_by(key="old").count() == 0


class _Request:
    def __init__(self, host, forwarded=None):
        self.client = type("C", (), {"host": host})()
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


def test_the_client_is_the_socket_peer_unless_proxies_are_trusted(monkeypatch):
    monkeypatch.setattr(rate_limit_module.get_settings(), "trusted_proxy_count", 0)

    assert client_ip(_Request("9.9.9.9", "1.1.1.1")) == "9.9.9.9"


def test_behind_one_proxy_the_address_the_proxy_appended_is_used_not_the_spoofed_one(monkeypatch):
    monkeypatch.setattr(rate_limit_module.get_settings(), "trusted_proxy_count", 1)

    # "6.6.6.6" is whatever the visitor claimed; the proxy appended the real peer last.
    assert client_ip(_Request("10.0.0.1", "6.6.6.6, 1.1.1.1")) == "1.1.1.1"


def test_a_missing_forwarded_header_falls_back_to_the_peer(monkeypatch):
    monkeypatch.setattr(rate_limit_module.get_settings(), "trusted_proxy_count", 1)

    assert client_ip(_Request("10.0.0.1")) == "10.0.0.1"


@pytest.fixture
def shop(db):
    tenant = Tenant(name="Shop", api_key=generate_api_key())
    db.add(tenant)
    db.flush()
    customer = Customer(name="Ana", email="ana@shop.test", tenant_id=tenant.id)
    db.add(customer)
    db.commit()
    return {"tenant": tenant, "customer": customer}


def test_starting_conversations_is_limited_per_address(shop):
    body = {"api_key": shop["tenant"].api_key}
    statuses = [client.post("/api/conversations", json=body).status_code for _ in range(21)]

    assert statuses[:20] == [200] * 20
    assert statuses[20] == 429


def test_a_limited_request_gets_a_retry_after_and_a_stable_code(shop):
    body = {"api_key": shop["tenant"].api_key}
    for _ in range(20):
        client.post("/api/conversations", json=body)

    response = client.post("/api/conversations", json=body)

    assert response.status_code == 429
    assert response.json()["detail"] == {"code": "rate_limited"}
    assert 1 <= int(response.headers["Retry-After"]) <= 3600


def test_a_flood_of_wrong_codes_from_one_address_is_cut_off(shop):
    body = {"api_key": shop["tenant"].api_key, "email": "ana@shop.test", "code": "000000"}
    statuses = [client.post("/api/auth/otp/verify", json=body).status_code for _ in range(21)]

    assert 429 in statuses and statuses[0] == 401


class _SilentGraph:
    """Ends every run without events: only the request handling is under test."""

    async def astream_events(self, initial_state, config, version):
        return
        yield


def test_the_chat_is_limited_per_conversation(shop, monkeypatch):
    from app.api import chat as chat_module
    from app.auth.conversations import resolve_for_login

    monkeypatch.setattr(chat_module, "agent_graph", _SilentGraph())
    with SessionLocal() as db:
        conversation = resolve_for_login(
            db,
            tenant_id=shop["tenant"].id,
            customer_id=shop["customer"].id,
            level=IdentityLevel.STORE_LOGIN,
            conversation_id=None,
            now=datetime.now(UTC),
        )
    token, _ = issue_session_token(
        tenant_id=shop["tenant"].id,
        conversation_id=conversation.id,
        customer_id=shop["customer"].id,
        level=IdentityLevel.STORE_LOGIN,
        signing_key=get_settings().session_signing_key,
        ttl=timedelta(hours=1),
    )
    headers = {"Authorization": f"Bearer {token}"}

    statuses = [
        client.post(
            "/api/chat", json={"message": "hi", "message_id": str(uuid.uuid4())}, headers=headers
        ).status_code
        for _ in range(32)
    ]

    assert 429 not in statuses[:30] and statuses[30] == 429

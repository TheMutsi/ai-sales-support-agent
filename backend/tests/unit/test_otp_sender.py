import logging
import uuid
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.auth import otp_sender
from app.auth.otp_sender import LogOtpSender, NoOtpProvider, SmtpOtpSender, sender_for_tenant
from app.core.secrets import SecretUnreadable, encrypt_secret
from app.db.models import TenantSmtp


class FakeSmtp:
    """Stands in for smtplib.SMTP / SMTP_SSL and records what the sender did to it."""

    instances: ClassVar[list["FakeSmtp"]] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls, self.secure = host, port, [], context is not None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        self.calls.append(("send", message["To"], message["From"], message.get_content()))


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(otp_sender.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(otp_sender.smtplib, "SMTP_SSL", FakeSmtp)


def _config(**overrides) -> TenantSmtp:
    values = {
        "tenant_id": uuid.uuid4(), "host": "mail.shop.test", "port": 587, "security": "starttls",
        "username": "mailer", "password_encrypted": encrypt_secret("s3cret"),
        "from_address": "no-reply@shop.test",
    }
    return TenantSmtp(**{**values, **overrides})


def _picker(config, env):
    db = SimpleNamespace(get=lambda _model, _id: config)
    return sender_for_tenant(SimpleNamespace(app_env=env), db)(SimpleNamespace(id=uuid.uuid4()))


def test_the_dev_sender_logs_the_code_so_a_developer_can_read_it(caplog):
    with caplog.at_level(logging.INFO):
        LogOtpSender().send(email="ana@shop.test", code="123456")

    assert "123456" in caplog.text and "ana@shop.test" in caplog.text


def test_starttls_logs_in_with_the_decrypted_password_and_sends_the_code():
    SmtpOtpSender(_config()).send(email="ana@shop.test", code="123456")

    server = FakeSmtp.instances[0]
    assert (server.host, server.port) == ("mail.shop.test", 587)
    assert server.calls[:2] == [("starttls",), ("login", "mailer", "s3cret")]
    _, to, sender, body = server.calls[2]
    assert (to, sender) == ("ana@shop.test", "no-reply@shop.test") and "123456" in body


def test_ssl_skips_starttls_and_no_credentials_skips_login():
    SmtpOtpSender(_config(security="ssl", username=None, password_encrypted=None)).send(
        email="ana@shop.test", code="123456"
    )

    server = FakeSmtp.instances[0]
    assert server.secure and [call[0] for call in server.calls] == ["send"]


def test_a_password_that_cannot_be_decrypted_fails_before_anything_is_sent():
    with pytest.raises(SecretUnreadable):
        SmtpOtpSender(_config(password_encrypted="garbage")).send(email="a@b.test", code="1")
    assert FakeSmtp.instances == []


def test_a_tenant_with_a_mail_server_uses_it_and_one_without_gets_the_dev_sender_locally():
    assert isinstance(_picker(_config(), "development"), SmtpOtpSender)
    assert isinstance(_picker(None, "development"), LogOtpSender)


def test_outside_local_environments_a_tenant_without_a_mail_server_cannot_send():
    sender = _picker(None, "production")

    assert isinstance(sender, NoOtpProvider)
    with pytest.raises(RuntimeError, match="email provider"):
        sender.send(email="a@b.test", code="1")

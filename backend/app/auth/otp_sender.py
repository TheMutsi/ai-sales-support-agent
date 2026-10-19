"""How a one-time code reaches the customer. The service only knows the
`OtpSender` interface; each tenant's mail server (`TenantSmtp`) is picked when a code is sent."""

import logging
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.config import LOCAL_ENVIRONMENTS, Settings
from app.core.secrets import decrypt_secret
from app.db.models import Tenant, TenantSmtp

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 10
SMTP_SECURITY = ("starttls", "ssl", "none")


class OtpSender(Protocol):
    def send(self, *, email: str, code: str) -> None: ...


class LogOtpSender:
    """Development only: prints the code to the server log instead of sending an email."""

    def send(self, *, email: str, code: str) -> None:
        logger.info("OTP for %s: %s", email, code)


class NoOtpProvider:
    """A tenant with no mail server outside local environments. Logging codes there would hand
    them to anyone who reads the logs, so sending fails (and is logged by the caller)."""

    def send(self, *, email: str, code: str) -> None:
        raise RuntimeError("No email provider is configured for this tenant.")


class SmtpOtpSender:
    """Sends the code through the tenant's mail server. The password is decrypted here, at the
    moment of sending, so a value that cannot be read fails like any other delivery problem."""

    def __init__(self, config: TenantSmtp) -> None:
        self._config = config

    def send(self, *, email: str, code: str) -> None:
        config = self._config
        message = EmailMessage()
        message["From"] = config.from_address
        message["To"] = email
        message["Subject"] = "Your verification code"
        message.set_content(f"Your verification code is {code}. It expires in a few minutes.")
        if config.security not in SMTP_SECURITY:
            raise ValueError(f"unknown smtp security {config.security!r}")
        # Credentials over a connection nobody encrypts would be readable on the way: refuse.
        has_credentials = bool(config.username or config.password_encrypted)
        if config.security == "none" and has_credentials:
            raise ValueError("smtp credentials need starttls or ssl")
        if bool(config.username) != bool(config.password_encrypted):
            raise ValueError("smtp username and password must be set together")
        password = decrypt_secret(config.password_encrypted) if config.password_encrypted else None
        context = ssl.create_default_context()
        if config.security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS, context=context
            )
        else:
            server = smtplib.SMTP(config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS)
        with server:
            if config.security == "starttls":
                server.starttls(context=context)
            if config.username and password:
                server.login(config.username, password)
            server.send_message(message)


def sender_for_tenant(settings: Settings, db: Session) -> Callable[[Tenant], OtpSender]:
    """Picks the tenant's mail server; without one, the log in local environments only."""

    def pick(tenant: Tenant) -> OtpSender:
        config = db.get(TenantSmtp, tenant.id)
        if config is not None:
            return SmtpOtpSender(config)
        return LogOtpSender() if settings.app_env in LOCAL_ENVIRONMENTS else NoOtpProvider()

    return pick

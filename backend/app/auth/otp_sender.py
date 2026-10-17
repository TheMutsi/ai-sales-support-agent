"""How a one-time code reaches the customer. The service only knows the
`OtpSender` interface, so a real email provider can replace the dev one without
touching the OTP logic."""

import logging
from typing import Protocol

from app.core.config import LOCAL_ENVIRONMENTS, Settings

logger = logging.getLogger(__name__)


class OtpSender(Protocol):
    def send(self, *, email: str, code: str) -> None: ...


class LogOtpSender:
    """Development only: prints the code to the server log instead of sending an email."""

    def send(self, *, email: str, code: str) -> None:
        logger.info("OTP for %s: %s", email, code)


def get_otp_sender(settings: Settings) -> OtpSender:
    if settings.app_env in LOCAL_ENVIRONMENTS:
        return LogOtpSender()
    # Logging codes outside local environments would hand them to anyone who reads
    # the logs, so fail loudly until a real provider is wired in.
    raise RuntimeError("No email provider is configured for one-time codes.")

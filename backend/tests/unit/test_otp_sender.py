import logging

import pytest

from app.auth.otp_sender import LogOtpSender, get_otp_sender
from app.core.config import Settings


def test_the_dev_sender_logs_the_code_so_a_developer_can_read_it(caplog):
    with caplog.at_level(logging.INFO):
        LogOtpSender().send(email="ana@shop.test", code="123456")

    assert "123456" in caplog.text and "ana@shop.test" in caplog.text


def test_local_environments_get_the_dev_sender():
    assert isinstance(get_otp_sender(Settings(app_env="development")), LogOtpSender)


def test_other_environments_refuse_to_log_codes_until_a_real_provider_exists():
    production = Settings(app_env="production", session_signing_key="p" * 32)

    with pytest.raises(RuntimeError, match="email provider"):
        get_otp_sender(production)

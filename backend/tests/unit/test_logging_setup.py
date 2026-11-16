import logging

import app.main  # noqa: F401  (importing it configures logging)


def test_the_apps_own_info_messages_are_shown_but_other_libraries_stay_quiet():
    assert logging.getLogger("app.auth.otp_sender").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)

"""Unit tests for findpapers.utils.logging_config."""

from __future__ import annotations

import logging

from findpapers.utils.logging_config import _NOISY_LOGGERS, configure_verbose_logging


class TestConfigureVerboseLogging:
    """Tests for configure_verbose_logging()."""

    def test_root_logger_set_to_debug(self) -> None:
        """Root logger level should be set to DEBUG after calling configure_verbose_logging."""
        original_level = logging.getLogger().level
        try:
            logging.getLogger().setLevel(logging.WARNING)
            configure_verbose_logging()
            assert logging.getLogger().level == logging.DEBUG
        finally:
            logging.getLogger().setLevel(original_level)

    def test_noisy_loggers_set_to_warning(self) -> None:
        """Known noisy third-party loggers should be set to WARNING."""
        configure_verbose_logging()
        for name in _NOISY_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING

    def test_noisy_loggers_list_is_not_empty(self) -> None:
        """The noisy loggers tuple should contain known entries."""
        assert len(_NOISY_LOGGERS) > 0
        assert "urllib3" in _NOISY_LOGGERS

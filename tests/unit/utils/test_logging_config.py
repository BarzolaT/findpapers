"""Unit tests for findpapers.utils.logging_config."""

from __future__ import annotations

import logging

from findpapers.utils.logging_config import (
    _NOISY_LOGGERS,
    SENSITIVE_PARAM_NAMES,
    SensitiveDataFilter,
    _SanitizingHandler,
    configure_verbose_logging,
    sanitize_message,
)


def _save_root_state() -> tuple[int, list[logging.Handler]]:
    """Save the root logger's level and handler list for later restoration."""
    root = logging.getLogger()
    return root.level, root.handlers[:]


def _restore_root_state(level: int, handlers: list[logging.Handler]) -> None:
    """Restore the root logger to a previously saved state."""
    root = logging.getLogger()
    root.setLevel(level)
    for h in root.handlers[:]:
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)


class TestConfigureVerboseLogging:
    """Tests for configure_verbose_logging()."""

    def test_root_logger_set_to_debug(self) -> None:
        """Root logger level should be set to DEBUG after calling configure_verbose_logging."""
        saved_level, saved_handlers = _save_root_state()
        try:
            logging.getLogger().setLevel(logging.WARNING)
            # Remove all handlers so the StreamHandler-add path is exercised.
            for h in logging.getLogger().handlers[:]:
                logging.getLogger().removeHandler(h)
            configure_verbose_logging()
            assert logging.getLogger().level == logging.DEBUG
        finally:
            _restore_root_state(saved_level, saved_handlers)

    def test_adds_stderr_handler_to_root_when_none_exists(self) -> None:
        """configure_verbose_logging() adds a StreamHandler to root when absent."""
        import sys

        saved_level, saved_handlers = _save_root_state()
        try:
            for h in logging.getLogger().handlers[:]:
                logging.getLogger().removeHandler(h)
            configure_verbose_logging()
            root_handlers = logging.getLogger().handlers
            has_stderr = any(
                isinstance(h, logging.StreamHandler)
                and getattr(h, "stream", None) in {sys.stdout, sys.stderr}
                for h in root_handlers
            )
            assert has_stderr, (
                "Root logger should have a stderr StreamHandler after configure_verbose_logging()"
            )
        finally:
            _restore_root_state(saved_level, saved_handlers)

    def test_does_not_add_duplicate_handler(self) -> None:
        """configure_verbose_logging() is idempotent: calling it twice adds only one handler."""
        saved_level, saved_handlers = _save_root_state()
        try:
            for h in logging.getLogger().handlers[:]:
                logging.getLogger().removeHandler(h)
            configure_verbose_logging()
            count_after_first = len(logging.getLogger().handlers)
            configure_verbose_logging()
            assert len(logging.getLogger().handlers) == count_after_first, (
                "configure_verbose_logging() should not add a duplicate handler"
            )
        finally:
            _restore_root_state(saved_level, saved_handlers)

    def test_noisy_loggers_set_to_warning(self) -> None:
        """Known noisy third-party loggers should be set to WARNING."""
        saved_level, saved_handlers = _save_root_state()
        try:
            configure_verbose_logging()
            for name in _NOISY_LOGGERS:
                assert logging.getLogger(name).level == logging.WARNING
        finally:
            _restore_root_state(saved_level, saved_handlers)

    def test_noisy_loggers_list_is_not_empty(self) -> None:
        """The noisy loggers tuple should contain known entries."""
        assert len(_NOISY_LOGGERS) > 0
        assert "urllib3" in _NOISY_LOGGERS


class TestSanitizeMessage:
    """Tests for sanitize_message()."""

    def test_redacts_apikey_query_param(self) -> None:
        """The 'apikey' query parameter value should be replaced and the secret absent."""
        text = "403 Forbidden for url: https://example.com/api?query=foo&apikey=supersecret"
        result = sanitize_message(text)
        assert "supersecret" not in result
        assert "apikey=" in result
        assert "query=foo" in result

    def test_redacts_api_key_query_param(self) -> None:
        """The 'api_key' query parameter value should be replaced and the secret absent."""
        text = "error: https://example.com/search?q=test&api_key=topsecret"
        result = sanitize_message(text)
        assert "topsecret" not in result
        assert "api_key=" in result

    def test_case_insensitive_param_name(self) -> None:
        """Sensitive param names should be matched case-insensitively."""
        text = "https://example.com/path?APIKEY=mykey&other=value"
        result = sanitize_message(text)
        assert "mykey" not in result
        assert "other=value" in result

    def test_leaves_non_sensitive_params_intact(self) -> None:
        """Non-sensitive query parameters should not be altered."""
        text = "https://example.com/path?query=machine+learning&start=0"
        result = sanitize_message(text)
        assert result == text

    def test_no_url_in_text(self) -> None:
        """Plain text without URLs should pass through unchanged."""
        text = "Something went wrong: connection timed out"
        assert sanitize_message(text) == text

    def test_url_without_query_string(self) -> None:
        """URLs with no query string should pass through unchanged."""
        text = "Request sent to https://example.com/api/v1/search"
        assert sanitize_message(text) == text

    def test_multiple_urls_in_text(self) -> None:
        """All URLs in text should have their sensitive params redacted."""
        text = "First: https://a.com/x?apikey=k1 Second: https://b.com/y?apikey=k2&page=1"
        result = sanitize_message(text)
        assert "k1" not in result
        assert "k2" not in result
        assert "page=1" in result


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter."""

    def _make_record(self, msg: str, *args: object) -> logging.LogRecord:
        """Create a minimal LogRecord for testing."""
        record = logging.LogRecord(
            name="findpapers.test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg=msg,
            args=args,
            exc_info=None,
        )
        return record

    def test_filter_returns_true(self) -> None:
        """filter() must always return True to allow the record through."""
        f = SensitiveDataFilter()
        record = self._make_record("hello")
        assert f.filter(record) is True

    def test_sanitizes_url_in_formatted_message(self) -> None:
        """Keys embedded via %s args should be redacted in record.msg."""
        f = SensitiveDataFilter()
        url = "https://example.com/api?apikey=secret"
        record = self._make_record("Request failed: %s", url)
        f.filter(record)
        assert "secret" not in record.msg
        assert "apikey=" in record.msg
        assert record.args is None

    def test_plain_message_unchanged(self) -> None:
        """Messages without URLs should be left unchanged by the filter."""
        f = SensitiveDataFilter()
        record = self._make_record("Search complete: %d results", 42)
        f.filter(record)
        assert "42" in record.msg
        assert record.args is None

    def test_sanitizing_handler_attached_to_findpapers_logger(self) -> None:
        """The findpapers root logger should have a _SanitizingHandler installed.

        Handlers (unlike filters) are invoked for propagated records from child
        loggers, which is required for records emitted by e.g.
        ``findpapers.connectors.ieee`` to be sanitized.
        """
        findpapers_logger = logging.getLogger("findpapers")
        assert any(isinstance(h, _SanitizingHandler) for h in findpapers_logger.handlers)

    def test_sensitive_param_names_is_not_empty(self) -> None:
        """SENSITIVE_PARAM_NAMES must contain known credential param names."""
        assert "apikey" in SENSITIVE_PARAM_NAMES
        assert "api_key" in SENSITIVE_PARAM_NAMES

    def test_child_logger_records_are_sanitized(self) -> None:
        """Records from child loggers must be sanitized before reaching handlers.

        This is the key regression test: logger-level filters are NOT invoked
        for propagated records; only handlers are.  The _SanitizingHandler on
        the 'findpapers' logger must sanitize records from e.g.
        'findpapers.connectors.ieee' before they reach any output handler.
        """
        import logging

        captured: list[str] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        child_logger = logging.getLogger("findpapers.connectors._test_sanitize")
        root_handler = _CapturingHandler()
        root_handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(root_handler)
        try:
            child_logger.warning(
                "Failed: %s",
                "https://api.example.com/v1?query=ml&apikey=mytopsecret",
            )
        finally:
            logging.getLogger().removeHandler(root_handler)

        assert len(captured) == 1
        assert "mytopsecret" not in captured[0]
        assert "apikey=" in captured[0]

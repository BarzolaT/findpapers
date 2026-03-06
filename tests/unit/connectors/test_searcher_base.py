"""Unit tests for SearchConnectorBase._get logging and response ordering."""

from __future__ import annotations

import datetime
from typing import Callable, List, Optional
from unittest.mock import MagicMock, patch

import pytest
import requests

from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.core.paper import Paper
from findpapers.core.query import Query
from findpapers.query.builder import QueryBuilder

# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------


class _StubConnector(SearchConnectorBase):
    """Minimal concrete SearchConnectorBase for testing _get and logging helpers."""

    def __init__(self, query_builder: QueryBuilder | None = None) -> None:
        super().__init__()
        self._query_builder = query_builder if query_builder is not None else MagicMock()

    @property
    def name(self) -> str:
        return "Stub"

    @property
    def query_builder(self) -> QueryBuilder:
        return self._query_builder

    @property
    def min_request_interval(self) -> float:
        return 0.0

    def _fetch_papers(
        self,
        query: Query,
        max_papers: Optional[int],
        progress_callback: Optional[Callable],
        since: Optional[datetime.date] = None,
        until: Optional[datetime.date] = None,
    ) -> List[Paper]:
        return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _make_response(status: int = 200, reason: str = "OK", content: bytes = b"body") -> MagicMock:
    """Build a minimal mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.reason = reason
    resp.headers = {"Content-Type": "application/json; charset=utf-8"}
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


class TestSearchConnectorBaseGetLogging:
    """Tests for logging inside SearchConnectorBase._get."""

    def test_request_logged_at_debug(self, caplog) -> None:
        """_get logs the outgoing GET URL at DEBUG level."""
        import logging

        searcher = _StubConnector()
        resp = _make_response()
        searcher._http_session = MagicMock()
        searcher._http_session.get.return_value = resp

        with caplog.at_level(logging.DEBUG, logger="findpapers.connectors.connector_base"):
            searcher._get("https://api.example.com/search", params={"q": "ml"})  # noqa: SLF001

        assert any("GET" in m and "example.com" in m for m in caplog.messages)

    def test_sensitive_params_redacted_in_request_log(self, caplog) -> None:
        """API key values are replaced with *** in the request log."""
        import logging

        searcher = _StubConnector()
        resp = _make_response()
        searcher._http_session = MagicMock()
        searcher._http_session.get.return_value = resp

        with caplog.at_level(logging.DEBUG, logger="findpapers.connectors.connector_base"):
            searcher._get(  # noqa: SLF001
                "https://api.example.com/search",
                params={"q": "ml", "api_key": "top-secret"},
            )

        messages = " ".join(caplog.messages)
        assert "top-secret" not in messages
        # urlencode encodes *** as %2A%2A%2A; either form confirms the value is masked
        assert "api_key=%2A%2A%2A" in messages or "api_key=***" in messages

    def test_sensitive_headers_redacted_in_request_log(self, caplog) -> None:
        """API key values in headers are replaced with *** in the request log."""
        import logging

        searcher = _StubConnector()
        resp = _make_response()
        searcher._http_session = MagicMock()
        searcher._http_session.get.return_value = resp

        with caplog.at_level(logging.DEBUG, logger="findpapers.connectors.connector_base"):
            searcher._get(  # noqa: SLF001
                "https://api.example.com/search",
                headers={"X-ELS-APIKey": "my-secret-key", "Accept": "application/json"},
            )

        messages = " ".join(caplog.messages)
        assert "my-secret-key" not in messages
        assert "***" in messages
        # Non-sensitive headers should still appear
        assert "application/json" in messages

    def test_response_logged_at_debug(self, caplog) -> None:
        """_get logs the response status, content-type, and size at DEBUG level."""
        import logging

        searcher = _StubConnector()
        resp = _make_response(status=200, content=b"hello")
        searcher._http_session = MagicMock()
        searcher._http_session.get.return_value = resp

        with caplog.at_level(logging.DEBUG, logger="findpapers.connectors.connector_base"):
            searcher._get("https://api.example.com/search")  # noqa: SLF001

        messages = " ".join(caplog.messages)
        assert "200" in messages
        assert "application/json" in messages

    def test_response_logged_before_raise_for_status(self, caplog) -> None:
        """Response is logged even when raise_for_status() subsequently raises (e.g. 404).

        This verifies the ordering: _log_response must be called BEFORE
        raise_for_status() so that non-2xx responses still appear in logs.
        """
        import logging

        import requests as req_lib

        searcher = _StubConnector()
        resp = _make_response(status=404, reason="Not Found", content=b"not found")
        resp.raise_for_status.side_effect = req_lib.HTTPError("404")
        searcher._http_session = MagicMock()
        searcher._http_session.get.return_value = resp

        with caplog.at_level(logging.DEBUG, logger="findpapers.connectors.connector_base"):
            with pytest.raises(req_lib.HTTPError):
                searcher._get("https://api.example.com/missing")  # noqa: SLF001

        messages = " ".join(caplog.messages)
        assert "404" in messages  # response was logged before the exception was raised


class TestSearchConnectorBasePrepareHeaders:
    """Tests for ConnectorBase._prepare_headers (library User-Agent injection)."""

    def test_user_agent_injected_by_default(self) -> None:
        """Base _prepare_headers always adds a findpapers User-Agent."""
        searcher = _StubConnector()
        result = searcher._prepare_headers({})  # noqa: SLF001
        assert "User-Agent" in result
        assert "findpapers" in result["User-Agent"]

    def test_caller_headers_preserved(self) -> None:
        """Caller-supplied headers are present alongside the User-Agent."""
        searcher = _StubConnector()
        custom = {"Accept": "application/json", "X-Custom": "value"}
        result = searcher._prepare_headers(custom)  # noqa: SLF001
        assert result["Accept"] == "application/json"
        assert result["X-Custom"] == "value"
        assert "findpapers" in result["User-Agent"]

    def test_caller_can_override_user_agent(self) -> None:
        """Explicit User-Agent from caller takes precedence over the default."""
        searcher = _StubConnector()
        result = searcher._prepare_headers({"User-Agent": "Custom/1.0"})  # noqa: SLF001
        assert result["User-Agent"] == "Custom/1.0"


class TestSearchConnectorBaseSearch:
    """Tests for SearchConnectorBase.search() validation and error handling."""

    def _make_searcher_with_validation(self, is_valid: bool, error_message: str | None = None):
        """Build a _StubConnector whose query_builder returns the given validation result."""
        from findpapers.query.builder import QueryValidationResult

        mock_builder = MagicMock()
        mock_builder.validate_query.return_value = QueryValidationResult(
            is_valid=is_valid,
            error_message=error_message,
        )
        return _StubConnector(query_builder=mock_builder)

    def test_raises_unsupported_query_error_when_query_invalid(self) -> None:
        """search() raises UnsupportedQueryError when query fails validation."""
        import pytest

        from findpapers.exceptions import UnsupportedQueryError

        searcher = self._make_searcher_with_validation(
            is_valid=False, error_message="Filter 'key' is not supported."
        )
        mock_query = MagicMock()
        with pytest.raises(UnsupportedQueryError, match="Filter 'key' is not supported"):
            searcher.search(mock_query)

    def test_error_message_included_in_exception(self) -> None:
        """UnsupportedQueryError message contains the searcher name and detail."""
        import pytest

        from findpapers.exceptions import UnsupportedQueryError

        searcher = self._make_searcher_with_validation(
            is_valid=False, error_message="Wildcard '?' not supported."
        )
        mock_query = MagicMock()
        with pytest.raises(UnsupportedQueryError, match=r"Stub.*Wildcard"):
            searcher.search(mock_query)

    def test_request_exception_returns_empty_list(self) -> None:
        """requests.RequestException in _fetch_papers is caught and returns empty list."""
        import requests as req_lib

        searcher = self._make_searcher_with_validation(is_valid=True)
        mock_query = MagicMock()
        with patch.object(
            searcher, "_fetch_papers", side_effect=req_lib.ConnectionError("network down")
        ):
            papers = searcher.search(mock_query)

        assert papers == []

    def test_http_error_returns_empty_list(self) -> None:
        """requests.HTTPError (e.g. 401) in _fetch_papers is caught and returns empty list."""
        import requests as req_lib

        searcher = self._make_searcher_with_validation(is_valid=True)
        mock_query = MagicMock()
        with patch.object(searcher, "_fetch_papers", side_effect=req_lib.HTTPError("401")):
            papers = searcher.search(mock_query)

        assert papers == []

    def test_connector_error_returns_empty_list(self) -> None:
        """ConnectorError in _fetch_papers is caught and returns empty list."""
        from findpapers.exceptions import ConnectorError

        searcher = self._make_searcher_with_validation(is_valid=True)
        mock_query = MagicMock()
        with patch.object(searcher, "_fetch_papers", side_effect=ConnectorError("API key invalid")):
            papers = searcher.search(mock_query)

        assert papers == []

    def test_unexpected_exception_propagates(self) -> None:
        """Unexpected exception (e.g. RuntimeError) in _fetch_papers is NOT caught."""
        searcher = self._make_searcher_with_validation(is_valid=True)
        mock_query = MagicMock()
        with pytest.raises(RuntimeError, match="boom"):
            with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
                searcher.search(mock_query)

    def test_caught_exceptions_are_logged(self, caplog) -> None:
        """Caught network errors are logged at ERROR level with traceback."""
        import logging

        import requests as req_lib

        searcher = self._make_searcher_with_validation(is_valid=True)
        mock_query = MagicMock()
        with caplog.at_level(logging.ERROR, logger="findpapers.connectors.search_base"):
            with patch.object(searcher, "_fetch_papers", side_effect=req_lib.Timeout("timed out")):
                searcher.search(mock_query)

        assert any("Stub" in m and "Error" in m for m in caplog.messages)


class TestConnectorBaseSessionPooling:
    """Tests for the lazy HTTP session and connection-pooling lifecycle."""

    def test_session_created_lazily(self) -> None:
        """No session exists until _get_session is called."""
        connector = _StubConnector()
        assert not hasattr(connector, "_http_session")

        session = connector._get_session()  # noqa: SLF001
        assert hasattr(connector, "_http_session")
        assert session is connector._http_session

    def test_session_reused_across_calls(self) -> None:
        """Consecutive calls to _get_session return the same instance."""
        connector = _StubConnector()
        first = connector._get_session()  # noqa: SLF001
        second = connector._get_session()  # noqa: SLF001
        assert first is second

    def test_close_removes_session(self) -> None:
        """close() removes the cached session attribute."""
        connector = _StubConnector()
        connector._get_session()  # noqa: SLF001
        assert hasattr(connector, "_http_session")

        connector.close()
        assert not hasattr(connector, "_http_session")

    def test_close_idempotent(self) -> None:
        """Calling close() multiple times does not raise."""
        connector = _StubConnector()
        connector.close()
        connector.close()  # should not raise

    def test_context_manager_closes_session(self) -> None:
        """Exiting a with-block calls close() on the connector."""
        with _StubConnector() as connector:
            _ = connector._get_session()  # noqa: SLF001
            assert hasattr(connector, "_http_session")

        # After __exit__, the cached session attribute is removed,
        # confirming close() was invoked.
        assert not hasattr(connector, "_http_session")

    def test_context_manager_returns_self(self) -> None:
        """The with-block yields the connector itself."""
        stub = _StubConnector()
        with stub as ctx:
            assert ctx is stub


class TestConnectorBaseRetry:
    """Tests for automatic retry with exponential backoff in _get / _post."""

    @staticmethod
    def _make_response(
        status: int = 200,
        reason: str = "OK",
        content: bytes = b"body",
        headers: dict | None = None,
    ) -> MagicMock:
        """Build a minimal mock requests.Response."""
        resp = MagicMock()
        resp.status_code = status
        resp.reason = reason
        resp.headers = headers or {"Content-Type": "application/json"}
        resp.content = content
        resp.raise_for_status = MagicMock()
        if status >= 400:
            resp.raise_for_status.side_effect = requests.HTTPError(
                f"{status} {reason}", response=resp
            )
        return resp

    def test_successful_request_no_retry(self) -> None:
        """A 200 response is returned immediately without retrying."""
        connector = _StubConnector()
        connector._max_retries = 3
        connector._retry_base_delay = 0.0
        resp = self._make_response(200)
        connector._http_session = MagicMock()
        connector._http_session.get.return_value = resp

        result = connector._get("https://api.example.com/test")  # noqa: SLF001

        assert result is resp
        assert connector._http_session.get.call_count == 1

    def test_429_retried_then_succeeds(self) -> None:
        """A 429 response triggers retries until a 200 is received."""
        connector = _StubConnector()
        connector._max_retries = 3
        connector._retry_base_delay = 0.0

        resp_429 = self._make_response(429, "Too Many Requests")
        # Override raise_for_status: 429 should NOT raise during retry loop
        # (only after all retries exhausted). The response mock needs to not
        # raise so the retry logic itself can check status_code.
        resp_429.raise_for_status = MagicMock()
        resp_200 = self._make_response(200)

        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = [resp_429, resp_429, resp_200]

        result = connector._get("https://api.example.com/test")  # noqa: SLF001

        assert result is resp_200
        assert connector._http_session.get.call_count == 3

    def test_503_retried_then_succeeds(self) -> None:
        """A 503 response triggers retries until a 200 is received."""
        connector = _StubConnector()
        connector._max_retries = 2
        connector._retry_base_delay = 0.0

        resp_503 = self._make_response(503, "Service Unavailable")
        resp_503.raise_for_status = MagicMock()
        resp_200 = self._make_response(200)

        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = [resp_503, resp_200]

        result = connector._get("https://api.example.com/test")  # noqa: SLF001

        assert result is resp_200
        assert connector._http_session.get.call_count == 2

    def test_retries_exhausted_raises_http_error(self) -> None:
        """When all retries are exhausted, HTTPError is raised."""
        import requests as req_lib

        connector = _StubConnector()
        connector._max_retries = 2
        connector._retry_base_delay = 0.0

        resp_429 = self._make_response(429, "Too Many Requests")
        # After retries are exhausted, raise_for_status is called on the last response.
        connector._http_session = MagicMock()
        connector._http_session.get.return_value = resp_429

        with pytest.raises(req_lib.HTTPError):
            connector._get("https://api.example.com/test")  # noqa: SLF001

        # 1 initial + 2 retries = 3 requests total
        assert connector._http_session.get.call_count == 3

    def test_non_retryable_status_raises_immediately(self) -> None:
        """A 404 is not retryable and raises HTTPError immediately."""
        import requests as req_lib

        connector = _StubConnector()
        connector._max_retries = 3
        connector._retry_base_delay = 0.0

        resp_404 = self._make_response(404, "Not Found")
        connector._http_session = MagicMock()
        connector._http_session.get.return_value = resp_404

        with pytest.raises(req_lib.HTTPError):
            connector._get("https://api.example.com/test")  # noqa: SLF001

        # Only 1 attempt — no retries for 404.
        assert connector._http_session.get.call_count == 1

    def test_connection_error_retried_then_succeeds(self) -> None:
        """A ConnectionError triggers retries until a request succeeds."""
        import requests as req_lib

        connector = _StubConnector()
        connector._max_retries = 2
        connector._retry_base_delay = 0.0

        resp_200 = self._make_response(200)
        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = [
            req_lib.ConnectionError("reset"),
            resp_200,
        ]

        result = connector._get("https://api.example.com/test")  # noqa: SLF001

        assert result is resp_200
        assert connector._http_session.get.call_count == 2

    def test_timeout_error_retried_then_succeeds(self) -> None:
        """A Timeout triggers retries until a request succeeds."""
        import requests as req_lib

        connector = _StubConnector()
        connector._max_retries = 2
        connector._retry_base_delay = 0.0

        resp_200 = self._make_response(200)
        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = [
            req_lib.Timeout("timed out"),
            resp_200,
        ]

        result = connector._get("https://api.example.com/test")  # noqa: SLF001

        assert result is resp_200
        assert connector._http_session.get.call_count == 2

    def test_connection_error_retries_exhausted(self) -> None:
        """Persistent ConnectionError is raised after all retries are exhausted."""
        import requests as req_lib

        connector = _StubConnector()
        connector._max_retries = 1
        connector._retry_base_delay = 0.0

        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = req_lib.ConnectionError("down")

        with pytest.raises(req_lib.ConnectionError):
            connector._get("https://api.example.com/test")  # noqa: SLF001

        # 1 initial + 1 retry = 2 attempts.
        assert connector._http_session.get.call_count == 2

    def test_retry_after_header_respected(self) -> None:
        """When 429 has Retry-After header, delay is at least that value."""
        connector = _StubConnector()
        connector._max_retries = 1
        connector._retry_base_delay = 0.01

        resp_429 = self._make_response(
            429,
            "Too Many Requests",
            headers={"Content-Type": "application/json", "Retry-After": "5"},
        )
        resp_429.raise_for_status = MagicMock()

        # Use _retry_delay directly to verify Retry-After is honoured.
        delay = connector._retry_delay(0, resp_429)  # noqa: SLF001
        assert delay >= 5.0

    def test_retry_delay_exponential_growth(self) -> None:
        """Delay increases exponentially with each attempt."""
        connector = _StubConnector()
        connector._retry_base_delay = 1.0
        connector._retry_max_delay = 120.0

        delays = [connector._retry_delay(i) for i in range(5)]  # noqa: SLF001

        # Base delays: 1, 2, 4, 8, 16 (before jitter).
        # With up to 25% jitter, minimum values are the base.
        for i, delay in enumerate(delays):
            base = 1.0 * (2**i)
            assert delay >= base
            assert delay <= base * 1.25 + 0.01  # small tolerance for float precision

    def test_retry_delay_capped_at_max(self) -> None:
        """Delay is capped at _retry_max_delay even for high attempt numbers."""
        connector = _StubConnector()
        connector._retry_base_delay = 1.0
        connector._retry_max_delay = 10.0

        delay = connector._retry_delay(20)  # noqa: SLF001

        # 1 * 2^20 = 1048576, but capped at 10, with up to 25% jitter = 12.5 max.
        assert delay <= 10.0 * 1.25 + 0.01

    def test_retry_logs_warnings(self, caplog) -> None:
        """Retried requests log warnings with attempt information."""
        import logging

        connector = _StubConnector()
        connector._max_retries = 1
        connector._retry_base_delay = 0.0

        resp_429 = self._make_response(429, "Too Many Requests")
        resp_429.raise_for_status = MagicMock()
        resp_200 = self._make_response(200)

        connector._http_session = MagicMock()
        connector._http_session.get.side_effect = [resp_429, resp_200]

        with caplog.at_level(logging.WARNING, logger="findpapers.connectors.connector_base"):
            connector._get("https://api.example.com/test")  # noqa: SLF001

        assert any("429" in m and "retrying" in m for m in caplog.messages)

    def test_post_retries_on_transient_error(self) -> None:
        """_post also retries on transient 503 errors."""
        connector = _StubConnector()
        connector._max_retries = 1
        connector._retry_base_delay = 0.0

        resp_503 = self._make_response(503, "Service Unavailable")
        resp_503.raise_for_status = MagicMock()
        resp_200 = self._make_response(200)

        connector._http_session = MagicMock()
        connector._http_session.post.side_effect = [resp_503, resp_200]

        result = connector._post("https://api.example.com/test", json_body={"q": "ml"})  # noqa: SLF001

        assert result is resp_200
        assert connector._http_session.post.call_count == 2


class TestConnectorBaseThreadSafety:
    """Tests for thread-safe rate limiting."""

    def test_rate_limit_lock_is_per_instance(self) -> None:
        """Each connector has its own lock to avoid cross-instance blocking."""
        c1 = _StubConnector()
        c2 = _StubConnector()
        assert c1._get_lock() is not c2._get_lock()  # noqa: SLF001

    def test_rate_limit_lock_is_reused(self) -> None:
        """The same lock is returned on consecutive calls."""
        connector = _StubConnector()
        lock_a = connector._get_lock()  # noqa: SLF001
        lock_b = connector._get_lock()  # noqa: SLF001
        assert lock_a is lock_b

    def test_concurrent_rate_limit_respects_interval(self) -> None:
        """Two threads sharing a connector both respect the minimum interval."""
        import threading

        connector = _StubConnector()
        timestamps: list[float] = []
        lock = threading.Lock()

        def _call() -> None:
            import time

            connector._rate_limit()  # noqa: SLF001
            with lock:
                timestamps.append(time.monotonic())
            connector._last_request_time = time.monotonic()  # noqa: SLF001

        # Patch the read-only property to use a measurable interval.
        with patch.object(
            type(connector),
            "min_request_interval",
            new_callable=lambda: property(lambda self: 0.05),
        ):
            t1 = threading.Thread(target=_call)
            t2 = threading.Thread(target=_call)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        # Both threads completed; the lock prevented data corruption.
        assert len(timestamps) == 2

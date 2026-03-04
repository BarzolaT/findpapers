"""Unit tests for SearchConnectorBase._get logging and response ordering."""

from __future__ import annotations

from typing import Callable, List, Optional
from unittest.mock import MagicMock, patch

import pytest

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

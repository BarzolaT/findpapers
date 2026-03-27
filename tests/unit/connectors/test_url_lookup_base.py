"""Unit tests for URLLookupConnectorBase."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from findpapers.connectors.url_lookup_base import URLLookupConnectorBase
from findpapers.core.paper import Paper


class _ConcreteURLConnector(URLLookupConnectorBase):
    """Minimal concrete implementation for testing the base class."""

    def __init__(self) -> None:
        super().__init__()
        self._fetch_paper_by_id_called_with: str | None = None
        self._return_paper: Paper | None = MagicMock(spec=Paper)

    @property
    def name(self) -> str:
        return "test_connector"

    @property
    def min_request_interval(self) -> float:
        return 0.0

    @property
    def url_pattern(self) -> re.Pattern[str]:
        # Matches URLs like https://example.com/paper/paper-id-999 and captures the ID.
        return re.compile(r"example\.com/paper/([\w-]+)", re.IGNORECASE)

    def fetch_paper_by_id(self, paper_id: str) -> Paper | None:
        self._fetch_paper_by_id_called_with = paper_id
        return self._return_paper


class TestURLLookupConnectorBaseFetchPaperByUrl:
    """Tests for the concrete fetch_paper_by_url method."""

    def test_matching_url_calls_fetch_paper_by_id(self) -> None:
        """fetch_paper_by_url delegates to fetch_paper_by_id when URL matches."""
        connector = _ConcreteURLConnector()
        result = connector.fetch_paper_by_url("https://example.com/paper/abc123")

        assert connector._fetch_paper_by_id_called_with == "abc123"
        assert result is connector._return_paper

    def test_non_matching_url_returns_none(self) -> None:
        """fetch_paper_by_url returns None when URL does not match the pattern."""
        connector = _ConcreteURLConnector()
        result = connector.fetch_paper_by_url("https://other-site.com/paper/abc123")

        assert connector._fetch_paper_by_id_called_with is None
        assert result is None

    def test_fetch_paper_by_id_returning_none_propagates(self) -> None:
        """None returned from fetch_paper_by_id is propagated to the caller."""
        connector = _ConcreteURLConnector()
        connector._return_paper = None
        result = connector.fetch_paper_by_url("https://example.com/paper/xyz")

        assert connector._fetch_paper_by_id_called_with == "xyz"
        assert result is None

    def test_first_capture_group_is_used_as_id(self) -> None:
        """The first capture group from the URL regex is passed to fetch_paper_by_id."""
        connector = _ConcreteURLConnector()
        connector.fetch_paper_by_url("https://example.com/paper/paper-id-999")
        assert connector._fetch_paper_by_id_called_with == "paper-id-999"


class TestURLLookupConnectorBaseSupportsUrl:
    """Tests for the concrete supports_url method."""

    def test_matching_url_returns_true(self) -> None:
        """supports_url returns True when the URL matches the connector's pattern."""
        connector = _ConcreteURLConnector()
        assert connector.supports_url("https://example.com/paper/abc123") is True

    def test_non_matching_url_returns_false(self) -> None:
        """supports_url returns False when the URL does not match the pattern."""
        connector = _ConcreteURLConnector()
        assert connector.supports_url("https://other-site.com/paper/abc123") is False

    def test_supports_url_does_not_call_fetch_paper_by_id(self) -> None:
        """supports_url only tests the pattern; it does not trigger a network call."""
        connector = _ConcreteURLConnector()
        connector.supports_url("https://example.com/paper/abc123")
        assert connector._fetch_paper_by_id_called_with is None

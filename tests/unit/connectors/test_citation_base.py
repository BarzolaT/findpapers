"""Tests for :class:`CitationConnectorBase` default implementations."""

from __future__ import annotations

from unittest.mock import MagicMock

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.core.paper import Paper


class _StubCitationConnector(CitationConnectorBase):
    """Minimal concrete subclass for testing defaults."""

    @property
    def name(self) -> str:
        """Return stub name."""
        return "stub"

    @property
    def min_request_interval(self) -> float:
        """Return zero interval."""
        return 0.0


class TestCitationConnectorBaseDefaults:
    """Default ``fetch_references`` / ``fetch_cited_by`` return empty lists."""

    def test_fetch_references_returns_empty_list(self) -> None:
        """Default fetch_references returns an empty list."""
        connector = _StubCitationConnector()
        paper = MagicMock(spec=Paper)
        result = connector.fetch_references(paper)
        assert result == []

    def test_fetch_cited_by_returns_empty_list(self) -> None:
        """Default fetch_cited_by returns an empty list."""
        connector = _StubCitationConnector()
        paper = MagicMock(spec=Paper)
        result = connector.fetch_cited_by(paper)
        assert result == []

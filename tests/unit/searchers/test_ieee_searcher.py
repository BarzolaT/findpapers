"""Unit tests for IEEESearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.ieee import IEEEQueryBuilder
from findpapers.searchers.ieee import IEEESearcher


class TestIEEESearcherInit:
    """Tests for IEEESearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates IEEEQueryBuilder when none provided."""
        searcher = IEEESearcher()
        assert isinstance(searcher.query_builder, IEEEQueryBuilder)

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = IEEESearcher(api_key="test_key")
        assert searcher._api_key == "test_key"

    def test_name(self):
        """Searcher name is 'IEEE'."""
        assert IEEESearcher().name == "IEEE"

    def test_is_available_without_api_key(self):
        """is_available is False when no API key is provided."""
        assert IEEESearcher().is_available is False

    def test_is_available_with_api_key(self):
        """is_available is True when an API key is provided."""
        assert IEEESearcher(api_key="key").is_available is True


class TestIEEESearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, ieee_sample_json):
        """Parsing sample JSON returns non-empty list of papers."""
        articles = ieee_sample_json.get("articles", [])
        assert len(articles) > 0

        papers = [IEEESearcher._parse_paper(item) for item in articles]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, ieee_sample_json):
        """Parsed paper has 'IEEE' in databases set."""
        item = ieee_sample_json["articles"][0]
        paper = IEEESearcher._parse_paper(item)
        assert paper is not None
        assert "IEEE" in paper.databases

    def test_missing_title_returns_none(self):
        """Item with empty title returns None."""
        paper = IEEESearcher._parse_paper({"title": "  ", "abstract": "some text"})
        assert paper is None


class TestIEEESearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_skipped_on_invalid_query(self, wildcard_query):
        """Search is aborted for '?' wildcard (not supported by IEEE)."""
        from findpapers.query.parser import QueryParser
        from findpapers.query.propagator import FilterPropagator

        parser = QueryParser()
        propagator = FilterPropagator()
        q = propagator.propagate(parser.parse("[mach?]"))
        searcher = IEEESearcher()
        papers = searcher.search(q)
        assert papers == []

    def test_search_returns_papers(self, simple_query, ieee_sample_json, mock_response):
        """search() returns papers from IEEE JSON response."""
        searcher = IEEESearcher()
        response = mock_response(json_data=ieee_sample_json)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.ieee.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all("IEEE" in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, ieee_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = IEEESearcher()
        response = mock_response(json_data=ieee_sample_json)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.ieee.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

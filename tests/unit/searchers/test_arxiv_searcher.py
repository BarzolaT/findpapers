"""Unit tests for ArxivSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.arxiv import ArxivQueryBuilder
from findpapers.searchers.arxiv import ArxivSearcher


class TestArxivSearcherInit:
    """Tests for ArxivSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates ArxivQueryBuilder when none provided."""
        searcher = ArxivSearcher()
        assert isinstance(searcher.query_builder, ArxivQueryBuilder)

    def test_custom_builder_used(self):
        """Searcher uses the provided builder."""
        builder = ArxivQueryBuilder()
        searcher = ArxivSearcher(query_builder=builder)
        assert searcher.query_builder is builder

    def test_name(self):
        """Searcher name is 'arXiv'."""
        assert ArxivSearcher().name == "arXiv"


class TestArxivSearcherParseResponse:
    """Tests for response parsing."""

    def test_parse_sample_xml(self, arxiv_sample_xml, simple_query):
        """Parsing sample XML returns non-empty list of papers."""
        from xml.etree import ElementTree as ET

        from findpapers.searchers.arxiv import _NS

        tree = ET.fromstring(arxiv_sample_xml)
        entries = tree.findall("atom:entry", _NS)
        assert len(entries) > 0

        papers = [ArxivSearcher._parse_paper(e) for e in entries]
        valid_papers = [p for p in papers if p is not None]
        assert len(valid_papers) > 0

    def test_parsed_paper_has_database_tag(self, arxiv_sample_xml):
        """Papers parsed from arXiv have 'arXiv' in databases set."""
        from xml.etree import ElementTree as ET

        from findpapers.searchers.arxiv import _NS

        tree = ET.fromstring(arxiv_sample_xml)
        entries = tree.findall("atom:entry", _NS)
        paper = ArxivSearcher._parse_paper(entries[0])
        assert paper is not None
        assert "arXiv" in paper.databases

    def test_missing_title_returns_none(self):
        """Entry without title returns None."""
        from xml.etree import ElementTree as ET

        xml_str = """
        <entry xmlns="http://www.w3.org/2005/Atom">
            <title>  </title>
            <summary>some abstract</summary>
        </entry>
        """
        entry = ET.fromstring(xml_str)
        assert ArxivSearcher._parse_paper(entry) is None


class TestArxivSearcherSearch:
    """Tests for the search() method with mocked HTTP calls."""

    def test_search_skipped_on_invalid_query(self, key_query):
        """Search returns empty list when query uses unsupported filter (key)."""
        searcher = ArxivSearcher()
        papers = searcher.search(key_query)
        assert papers == []

    def test_search_returns_papers_from_xml(self, simple_query, arxiv_sample_xml, mock_response):
        """Search parses XML response and returns papers."""
        searcher = ArxivSearcher()
        response = mock_response(text=arxiv_sample_xml)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.arxiv.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query, max_papers=5)

        assert len(papers) <= 5
        assert all("arXiv" in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, arxiv_sample_xml, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = ArxivSearcher()
        response = mock_response(text=arxiv_sample_xml)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.arxiv.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query, max_papers=3)

        assert len(papers) <= 3

    def test_progress_callback_called(self, simple_query, arxiv_sample_xml, mock_response):
        """search() invokes progress_callback during pagination."""
        searcher = ArxivSearcher()
        response = mock_response(text=arxiv_sample_xml)
        response.raise_for_status = MagicMock()
        callback_calls = []

        def _callback(current, total):
            callback_calls.append((current, total))

        with patch("findpapers.searchers.arxiv.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            searcher.search(simple_query, progress_callback=_callback)

        assert len(callback_calls) > 0

    def test_http_error_returns_empty(self, simple_query, mock_response):
        """search() returns empty list when HTTP request fails."""
        searcher = ArxivSearcher()
        import requests as req

        with patch(
            "findpapers.searchers.arxiv.requests.get", side_effect=req.HTTPError("500")
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert papers == []

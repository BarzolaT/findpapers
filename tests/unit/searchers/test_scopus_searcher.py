"""Unit tests for ScopusSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.scopus import ScopusQueryBuilder
from findpapers.searchers.scopus import ScopusSearcher


class TestScopusSearcherInit:
    """Tests for ScopusSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates ScopusQueryBuilder when none provided."""
        searcher = ScopusSearcher()
        assert isinstance(searcher.query_builder, ScopusQueryBuilder)

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = ScopusSearcher(api_key="test_key")
        assert searcher._api_key == "test_key"

    def test_name(self):
        """Searcher name is 'Scopus'."""
        assert ScopusSearcher().name == "Scopus"


class TestScopusSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, scopus_sample_json):
        """Parsing sample JSON returns non-empty list of papers."""
        entries = scopus_sample_json.get("search-results", {}).get("entry", [])
        assert len(entries) > 0

        papers = [ScopusSearcher._parse_paper(e) for e in entries]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, scopus_sample_json):
        """Parsed paper has 'Scopus' in databases set."""
        entry = scopus_sample_json["search-results"]["entry"][0]
        paper = ScopusSearcher._parse_paper(entry)
        assert paper is not None
        assert "Scopus" in paper.databases

    def test_missing_title_returns_none(self):
        """Entry with empty title returns None."""
        paper = ScopusSearcher._parse_paper({"dc:title": ""})
        assert paper is None


class TestScopusSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    @staticmethod
    def _empty_page_response(mock_response):
        """Create a mocked response containing no entries for pagination stop."""
        response = mock_response(json_data={"search-results": {"entry": []}})
        response.raise_for_status = MagicMock()
        return response

    def test_search_returns_papers(self, simple_query, scopus_sample_json, mock_response):
        """search() returns papers from Scopus JSON response."""
        searcher = ScopusSearcher()
        response_with_data = mock_response(json_data=scopus_sample_json)
        response_with_data.raise_for_status = MagicMock()
        response_empty_page = self._empty_page_response(mock_response)

        with patch.object(
            searcher,
            "_get",
            side_effect=[response_with_data, response_empty_page],
        ) as mocked_get, patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert mocked_get.call_count == 2
        assert len(papers) > 0
        assert all("Scopus" in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, scopus_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = ScopusSearcher()
        response_with_data = mock_response(json_data=scopus_sample_json)
        response_with_data.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response_with_data), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

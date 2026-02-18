"""Unit tests for OpenAlexSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.openalex import OpenAlexQueryBuilder
from findpapers.searchers.openalex import OpenAlexSearcher, _reconstruct_abstract


class TestOpenAlexSearcherInit:
    """Tests for OpenAlexSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates OpenAlexQueryBuilder when none provided."""
        searcher = OpenAlexSearcher()
        assert isinstance(searcher.query_builder, OpenAlexQueryBuilder)

    def test_email_stored(self):
        """Email is stored for polite pool requests."""
        searcher = OpenAlexSearcher(email="test@example.com")
        assert searcher._email == "test@example.com"

    def test_name(self):
        """Searcher name is 'OpenAlex'."""
        assert OpenAlexSearcher().name == "OpenAlex"


class TestOpenAlexSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, openalex_sample_json):
        """Parsing sample JSON results returns non-empty list of papers."""
        results = openalex_sample_json.get("results", [])
        assert len(results) > 0

        papers = [OpenAlexSearcher._parse_paper(r) for r in results]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, openalex_sample_json):
        """Parsed paper has 'OpenAlex' in databases set."""
        result = openalex_sample_json["results"][0]
        paper = OpenAlexSearcher._parse_paper(result)
        assert paper is not None
        assert "OpenAlex" in paper.databases

    def test_missing_title_returns_none(self):
        """Result with blank title returns None."""
        paper = OpenAlexSearcher._parse_paper({"title": "  "})
        assert paper is None


class TestOpenAlexSearcherReconstructAbstract:
    """Tests for _reconstruct_abstract helper."""

    def test_reconstruct_basic(self):
        """Inverted index is correctly reconstructed into a sentence."""
        inverted = {"Hello": [0], "world": [1]}
        result = _reconstruct_abstract(inverted)
        assert result == "Hello world"

    def test_reconstruct_returns_empty_on_none(self):
        """None inverted index returns empty string."""
        assert _reconstruct_abstract(None) == ""

    def test_reconstruct_returns_empty_on_empty_dict(self):
        """Empty dict returns empty string."""
        assert _reconstruct_abstract({}) == ""


class TestOpenAlexSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def _make_next_page_response(self, mock_response, empty: bool = False):
        """Build a response that signals no further pages."""
        data = {
            "meta": {"count": 0, "per_page": 25, "next_cursor": None},
            "results": [],
        }
        r = mock_response(json_data=data)
        r.raise_for_status = MagicMock()
        return r

    def test_search_returns_papers(self, simple_query, openalex_sample_json, mock_response):
        """search() returns papers from OpenAlex JSON response."""
        searcher = OpenAlexSearcher()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)

        with patch(
            "findpapers.searchers.openalex.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all("OpenAlex" in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, openalex_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = OpenAlexSearcher()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)

        with patch(
            "findpapers.searchers.openalex.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

"""Unit tests for SemanticScholarSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder
from findpapers.searchers.semantic_scholar import SemanticScholarSearcher


class TestSemanticScholarSearcherInit:
    """Tests for SemanticScholarSearcher initialisation."""

    def test_default_builder_created(self):
        """Searcher creates SemanticScholarQueryBuilder when none provided."""
        searcher = SemanticScholarSearcher()
        assert isinstance(searcher.query_builder, SemanticScholarQueryBuilder)

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = SemanticScholarSearcher(api_key="test_key")
        assert searcher._api_key == "test_key"

    def test_name(self):
        """Searcher name is 'Semantic Scholar'."""
        assert SemanticScholarSearcher().name == "Semantic Scholar"


class TestSemanticScholarSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, semantic_scholar_sample_json):
        """Parsing sample data entries returns non-empty list of papers."""
        data = semantic_scholar_sample_json.get("data", [])
        assert len(data) > 0

        papers = [SemanticScholarSearcher._parse_paper(item) for item in data]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, semantic_scholar_sample_json):
        """Parsed paper has 'Semantic Scholar' in databases set."""
        item = semantic_scholar_sample_json["data"][0]
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert "Semantic Scholar" in paper.databases

    def test_missing_title_returns_none(self):
        """Item with blank title returns None."""
        paper = SemanticScholarSearcher._parse_paper({"title": "", "abstract": "a"})
        assert paper is None


class TestSemanticScholarSearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def _empty_page(self, mock_response):
        """A response with no token and no data (signals last page)."""
        data = {"total": 0, "data": [], "token": None}
        r = mock_response(json_data=data)
        r.raise_for_status = MagicMock()
        return r

    def test_search_returns_papers(
        self,
        simple_query,
        semantic_scholar_sample_json,
        mock_response,
    ):
        """search() returns papers from Semantic Scholar bulk search response."""
        searcher = SemanticScholarSearcher()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)

        with patch(
            "findpapers.searchers.semantic_scholar.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all("Semantic Scholar" in p.databases for p in papers)

    def test_max_papers_respected(
        self,
        simple_query,
        semantic_scholar_sample_json,
        mock_response,
    ):
        """search() returns no more than max_papers papers."""
        searcher = SemanticScholarSearcher()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)

        with patch(
            "findpapers.searchers.semantic_scholar.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

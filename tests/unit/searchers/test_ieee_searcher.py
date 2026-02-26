"""Unit tests for IEEESearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from findpapers.core.paper import PaperType
from findpapers.core.search import Database
from findpapers.core.source import SourceType
from findpapers.exceptions import UnsupportedQueryError
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
        assert IEEESearcher().name == Database.IEEE

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

        papers = [IEEESearcher()._parse_paper(item) for item in articles]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, ieee_sample_json):
        """Parsed paper has 'IEEE' in databases set."""
        item = ieee_sample_json["articles"][0]
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert Database.IEEE in paper.databases

    def test_missing_title_returns_none(self):
        """Item with empty title returns None."""
        paper = IEEESearcher()._parse_paper({"title": "  ", "abstract": "some text"})
        assert paper is None

    def test_parse_with_all_keyword_groups(self):
        """Keywords from ieee_terms, author_terms and mesh_terms (nested in index_terms)."""
        item = {
            "title": "A Paper",
            "index_terms": {
                "ieee_terms": {"terms": ["term1"]},
                "author_terms": {"terms": ["term2"]},
                "mesh_terms": {"terms": ["term3"]},
            },
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.keywords is not None
        assert len(paper.keywords) == 3

    def test_pages_start_end(self):
        """start_page and end_page are combined into page_range field."""
        item = {"title": "A Paper", "start_page": "10", "end_page": "20"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.page_range == "10-20"

    def test_pages_start_only(self):
        """Only start_page populates page_range field."""
        item = {"title": "A Paper", "start_page": "5"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.page_range == "5"

    def test_citation_count_parsed(self):
        """citing_paper_count is parsed as an integer."""
        item = {"title": "A Paper", "citing_paper_count": "42"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.citations == 42

    def test_invalid_citation_count_ignored(self):
        """Non-numeric citing_paper_count is gracefully ignored."""
        item = {"title": "A Paper", "citing_paper_count": "N/A"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.citations is None

    def test_publication_fields_extracted(self):
        """Publication title, issn, isbn, and publisher are extracted."""
        item = {
            "title": "A Paper",
            "publication_title": "IEEE Trans.",
            "issn": "1234-5678",
            "isbn": "978-0-xxx",
            "publisher": "IEEE",
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "IEEE Trans."

    def test_keywords_from_sample_data(self, ieee_sample_json):
        """Keywords are extracted from nested index_terms in real sample data."""
        articles = ieee_sample_json["articles"]
        # articles[2] is the first entry with index_terms (ieee_terms + author_terms)
        paper = IEEESearcher()._parse_paper(articles[2])
        assert paper is not None
        assert paper.keywords is not None
        assert len(paper.keywords) > 0
        # Verify a known IEEE term from the sample
        assert "Natural language processing" in paper.keywords

    def test_source_type_journal(self):
        """content_type 'Journals' maps to SourceType.JOURNAL."""
        item = {"title": "A Paper", "publication_title": "IEEE Trans.", "content_type": "Journals"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.JOURNAL

    def test_source_type_conference(self):
        """content_type 'Conferences' maps to SourceType.CONFERENCE."""
        item = {
            "title": "A Paper",
            "publication_title": "Proc. ICML",
            "content_type": "Conferences",
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.CONFERENCE

    def test_source_type_book(self):
        """content_type 'Books' maps to SourceType.BOOK."""
        item = {"title": "A Paper", "publication_title": "A Book Title", "content_type": "Books"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.BOOK

    def test_source_type_magazine(self):
        """content_type 'Magazines' maps to SourceType.JOURNAL."""
        item = {
            "title": "A Paper",
            "publication_title": "IEEE Spectrum",
            "content_type": "Magazines",
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.JOURNAL

    def test_source_type_none_when_unknown(self):
        """Unknown content_type results in source_type being None."""
        item = {
            "title": "A Paper",
            "publication_title": "Something",
            "content_type": "UnknownType",
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type is None

    def test_source_type_standards_maps_to_other(self):
        """content_type 'Standards' maps to SourceType.OTHER."""
        item = {
            "title": "A Paper",
            "publication_title": "IEEE Standard",
            "content_type": "Standards",
        }
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.OTHER

    def test_paper_type_article_from_journals(self):
        """content_type 'Journals' maps to PaperType.ARTICLE."""
        item = {"title": "P", "content_type": "Journals"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_inproceedings_from_conferences(self):
        """content_type 'Conferences' maps to PaperType.INPROCEEDINGS."""
        item = {"title": "P", "content_type": "Conferences"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_inbook_from_books(self):
        """content_type 'Books' maps to PaperType.INBOOK."""
        item = {"title": "P", "content_type": "Books"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.INBOOK

    def test_paper_type_techreport_from_standards(self):
        """content_type 'Standards' maps to PaperType.TECHREPORT."""
        item = {"title": "P", "content_type": "Standards"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.TECHREPORT

    def test_paper_type_none_when_unknown(self):
        """Unknown content_type results in paper_type being None."""
        item = {"title": "P", "content_type": "UnknownType"}
        paper = IEEESearcher()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is None


class TestIEEESearcherSearch:
    """Tests for search() with mocked HTTP calls."""

    def test_search_raises_on_invalid_query(self, wildcard_query):
        """Search raises UnsupportedQueryError for '?' wildcard (not supported by IEEE)."""
        from findpapers.query.parser import QueryParser
        from findpapers.query.propagator import FilterPropagator

        parser = QueryParser()
        propagator = FilterPropagator()
        q = propagator.propagate(parser.parse("[mach?]"))
        searcher = IEEESearcher()
        with pytest.raises(UnsupportedQueryError):
            searcher.search(q)

    def test_search_returns_papers(self, simple_query, ieee_sample_json, mock_response):
        """search() returns papers from IEEE JSON response."""
        searcher = IEEESearcher()
        response = mock_response(json_data=ieee_sample_json)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.base.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all(Database.IEEE in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, ieee_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = IEEESearcher()
        response = mock_response(json_data=ieee_sample_json)
        response.raise_for_status = MagicMock()

        with patch("findpapers.searchers.base.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

    def test_http_error_breaks_loop(self, simple_query, mock_response):
        """HTTP error in _get breaks the pagination loop and returns partial results."""
        searcher = IEEESearcher()

        with patch.object(searcher, "_get", side_effect=Exception("network error")), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(self, simple_query, ieee_sample_json, mock_response):
        """Progress callback is called during search."""
        searcher = IEEESearcher()
        response = mock_response(json_data=ieee_sample_json)
        response.raise_for_status = MagicMock()
        callback = MagicMock()

        with patch("findpapers.searchers.base.requests.get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers is surfaced as an empty list."""
        searcher = IEEESearcher()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

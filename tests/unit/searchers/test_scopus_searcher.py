"""Unit tests for ScopusSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.core.paper import PaperType
from findpapers.core.search import Database
from findpapers.query.builders.scopus import ScopusQueryBuilder
from findpapers.searchers.scopus import ScopusSearcher, _scopus_aggregation_type_to_paper_type


class TestScopusAggregationTypeMapping:
    """Tests for _scopus_aggregation_type_to_paper_type helper."""

    def test_none_returns_none(self):
        """None input returns None."""
        assert _scopus_aggregation_type_to_paper_type(None) is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert _scopus_aggregation_type_to_paper_type("") is None

    def test_journal_maps_to_article(self):
        """'Journal' maps to PaperType.ARTICLE."""
        assert _scopus_aggregation_type_to_paper_type("Journal") == PaperType.ARTICLE

    def test_trade_journal_maps_to_article(self):
        """'Trade Journal' maps to PaperType.ARTICLE."""
        assert _scopus_aggregation_type_to_paper_type("Trade Journal") == PaperType.ARTICLE

    def test_conference_proceeding_maps_to_inproceedings(self):
        """'Conference Proceeding' maps to PaperType.INPROCEEDINGS."""
        assert (
            _scopus_aggregation_type_to_paper_type("Conference Proceeding")
            == PaperType.INPROCEEDINGS
        )

    def test_book_maps_to_incollection(self):
        """'Book' maps to PaperType.INCOLLECTION."""
        assert _scopus_aggregation_type_to_paper_type("Book") == PaperType.INCOLLECTION

    def test_book_series_maps_to_incollection(self):
        """'Book Series' maps to PaperType.INCOLLECTION."""
        assert _scopus_aggregation_type_to_paper_type("Book Series") == PaperType.INCOLLECTION

    def test_unknown_type_returns_none(self):
        """Unknown aggregation type returns None."""
        assert _scopus_aggregation_type_to_paper_type("Unknown") is None

    def test_case_insensitive(self):
        """Mapping is case-insensitive."""
        assert _scopus_aggregation_type_to_paper_type("JOURNAL") == PaperType.ARTICLE


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
        assert ScopusSearcher().name == Database.SCOPUS

    def test_is_available_without_api_key(self):
        """is_available is False when no API key is provided."""
        assert ScopusSearcher().is_available is False

    def test_is_available_with_api_key(self):
        """is_available is True when an API key is provided."""
        assert ScopusSearcher(api_key="key").is_available is True


class TestScopusSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, scopus_sample_json):
        """Parsing sample JSON returns non-empty list of papers."""
        entries = scopus_sample_json.get("search-results", {}).get("entry", [])
        assert len(entries) > 0

        papers = [ScopusSearcher()._parse_paper(e) for e in entries]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, scopus_sample_json):
        """Parsed paper has 'Scopus' in databases set."""
        entry = scopus_sample_json["search-results"]["entry"][0]
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert Database.SCOPUS in paper.databases

    def test_missing_title_returns_none(self):
        """Entry with empty title returns None."""
        paper = ScopusSearcher()._parse_paper({"dc:title": ""})
        assert paper is None

    def test_authors_as_list(self):
        """Entry with dc:creator as a list produces multiple authors."""
        entry = {
            "dc:title": "A Paper",
            "dc:creator": ["Author One", "Author Two"],
        }
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert len(paper.authors) == 2
        assert "Author One" in paper.authors

    def test_abstract_from_teaser_fallback(self):
        """Entry without dc:description uses prism:teaser for abstract."""
        entry = {
            "dc:title": "A Paper",
            "prism:teaser": "Teaser text here.",
        }
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert paper.abstract == "Teaser text here."

    def test_isbn_as_list_of_dicts(self):
        """Entry with prism:isbn as list of dicts extracts first value."""
        entry = {
            "dc:title": "A Book Chapter",
            "prism:publicationName": "Some Book",
            "prism:isbn": [{"$": "978-3-16-148410-0"}, {"$": "978-0-00-000000-0"}],
        }
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert paper.publication is not None
        assert paper.publication.isbn == "978-3-16-148410-0"

    def test_aggregation_type_conference(self):
        """Entry with Conference Proceeding aggregation maps to INPROCEEDINGS."""
        entry = {
            "dc:title": "A Conference Paper",
            "prism:aggregationType": "Conference Proceeding",
        }
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert paper.paper_type == PaperType.INPROCEEDINGS

    def test_pages_extracted(self):
        """Entry with prism:pageRange populates pages field."""
        entry = {"dc:title": "A Paper", "prism:pageRange": "100-110"}
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert paper.pages == "100-110"

    def test_citation_count_parsed(self):
        """citedby-count is parsed as integer."""
        entry = {"dc:title": "A Paper", "citedby-count": "42"}
        paper = ScopusSearcher()._parse_paper(entry)
        assert paper is not None
        assert paper.citations == 42


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
        assert all(Database.SCOPUS in p.databases for p in papers)

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

    def test_http_error_breaks_loop(self, simple_query):
        """Exception in _get breaks the pagination loop and returns empty list."""
        searcher = ScopusSearcher()

        with patch.object(searcher, "_get", side_effect=Exception("network error")), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(self, simple_query, scopus_sample_json, mock_response):
        """Progress callback is invoked after processing each page."""
        searcher = ScopusSearcher()
        response_with_data = mock_response(json_data=scopus_sample_json)
        response_with_data.raise_for_status = MagicMock()
        response_empty_page = self._empty_page_response(mock_response)
        callback = MagicMock()

        with patch.object(
            searcher,
            "_get",
            side_effect=[response_with_data, response_empty_page],
        ), patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_pagination_stops_on_short_page(self, simple_query, mock_response):
        """Pagination stops when fewer entries than page_size are returned."""
        single_entry_data = {
            "search-results": {
                "opensearch:totalResults": "1",
                "entry": [
                    {
                        "dc:title": "A Paper",
                        "dc:creator": "Some Author",
                        "prism:coverDate": "2023-01-01",
                    }
                ],
            }
        }
        searcher = ScopusSearcher()
        response = mock_response(json_data=single_entry_data)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        # The loop should stop after first page (1 entry < page_size=25)
        assert len(papers) <= 1

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = ScopusSearcher()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

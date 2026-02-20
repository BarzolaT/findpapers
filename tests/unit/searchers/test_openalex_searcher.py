"""Unit tests for OpenAlexSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.core.paper import PaperType
from findpapers.core.search import Database
from findpapers.query.builders.openalex import OpenAlexQueryBuilder
from findpapers.searchers.openalex import (
    OpenAlexSearcher,
    _openalex_work_type_to_paper_type,
    _reconstruct_abstract,
)


class TestOpenAlexWorkTypeMapping:
    """Tests for _openalex_work_type_to_paper_type helper."""

    def test_none_returns_none(self):
        """None input returns None."""
        assert _openalex_work_type_to_paper_type(None) is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert _openalex_work_type_to_paper_type("") is None

    def test_article_maps_to_article(self):
        """'article' maps to PaperType.ARTICLE."""
        assert _openalex_work_type_to_paper_type("article") == PaperType.ARTICLE

    def test_review_maps_to_article(self):
        """'review' maps to PaperType.ARTICLE."""
        assert _openalex_work_type_to_paper_type("review") == PaperType.ARTICLE

    def test_book_chapter_maps_to_incollection(self):
        """'book-chapter' maps to PaperType.INCOLLECTION."""
        assert _openalex_work_type_to_paper_type("book-chapter") == PaperType.INCOLLECTION

    def test_book_maps_to_inbook(self):
        """'book' maps to PaperType.INBOOK."""
        assert _openalex_work_type_to_paper_type("book") == PaperType.INBOOK

    def test_preprint_maps_to_unpublished(self):
        """'preprint' maps to PaperType.UNPUBLISHED."""
        assert _openalex_work_type_to_paper_type("preprint") == PaperType.UNPUBLISHED

    def test_dissertation_maps_to_phdthesis(self):
        """'dissertation' maps to PaperType.PHDTHESIS."""
        assert _openalex_work_type_to_paper_type("dissertation") == PaperType.PHDTHESIS

    def test_proceedings_article_maps_to_inproceedings(self):
        """'proceedings-article' maps to PaperType.INPROCEEDINGS."""
        assert _openalex_work_type_to_paper_type("proceedings-article") == PaperType.INPROCEEDINGS

    def test_report_maps_to_techreport(self):
        """'report' maps to PaperType.TECHREPORT."""
        assert _openalex_work_type_to_paper_type("report") == PaperType.TECHREPORT

    def test_standard_maps_to_techreport(self):
        """'standard' maps to PaperType.TECHREPORT."""
        assert _openalex_work_type_to_paper_type("standard") == PaperType.TECHREPORT

    def test_unknown_returns_none(self):
        """Unknown work type returns None."""
        assert _openalex_work_type_to_paper_type("dataset") is None

    def test_case_insensitive(self):
        """Mapping is case-insensitive."""
        assert _openalex_work_type_to_paper_type("ARTICLE") == PaperType.ARTICLE


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
        assert OpenAlexSearcher().name == Database.OPENALEX

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = OpenAlexSearcher(api_key="mykey")
        assert searcher._api_key == "mykey"


class TestOpenAlexPrepareHeaders:
    """Tests for _prepare_headers."""

    def test_default_user_agent(self):
        """Without email, default User-Agent is used."""
        headers = OpenAlexSearcher()._prepare_headers({})
        assert "findpapers" in headers["User-Agent"]

    def test_custom_user_agent_with_email(self):
        """With email, User-Agent contains the email address."""
        headers = OpenAlexSearcher(email="me@example.com")._prepare_headers({})
        assert "me@example.com" in headers["User-Agent"]


class TestOpenAlexSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, openalex_sample_json):
        """Parsing sample JSON results returns non-empty list of papers."""
        results = openalex_sample_json.get("results", [])
        assert len(results) > 0

        papers = [OpenAlexSearcher()._parse_paper(r) for r in results]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, openalex_sample_json):
        """Parsed paper has 'OpenAlex' in databases set."""
        result = openalex_sample_json["results"][0]
        paper = OpenAlexSearcher()._parse_paper(result)
        assert paper is not None
        assert Database.OPENALEX in paper.databases

    def test_missing_title_returns_none(self):
        """Result with blank title returns None."""
        paper = OpenAlexSearcher()._parse_paper({"title": "  "})
        assert paper is None

    def test_open_access_url_used(self):
        """oa_url from open_access is used as paper URL."""
        work = {
            "title": "A Paper",
            "open_access": {"oa_url": "https://example.com/paper.pdf"},
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.url == "https://example.com/paper.pdf"

    def test_landing_page_url_fallback(self):
        """primary_location.landing_page_url is fallback when oa_url absent."""
        work = {
            "title": "A Paper",
            "open_access": {},
            "primary_location": {"landing_page_url": "https://example.com/landing"},
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.url == "https://example.com/landing"

    def test_pdf_url_from_locations(self):
        """pdf_url is extracted from the first location with one."""
        work = {
            "title": "A Paper",
            "locations": [
                {"pdf_url": None},
                {"pdf_url": "https://example.com/paper.pdf"},
            ],
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_keywords_from_concepts_and_keywords(self):
        """Keywords collected from both concepts and keywords fields."""
        work = {
            "title": "A Paper",
            "concepts": [{"display_name": "Machine Learning"}],
            "keywords": [{"display_name": "Deep Learning"}],
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.keywords is not None
        assert "Machine Learning" in paper.keywords
        assert "Deep Learning" in paper.keywords

    def test_publication_from_primary_location_source(self):
        """Publication is built from primary_location.source."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {"display_name": "Nature", "issn_l": ["1234-5678"]},
                "landing_page_url": None,
            },
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.publication is not None
        assert paper.publication.title == "Nature"
        assert paper.publication.issn == "1234-5678"

    def test_doi_stripped_of_prefix(self):
        """DOI prefix 'https://doi.org/' is stripped."""
        work = {
            "title": "A Paper",
            "doi": "https://doi.org/10.1234/test",
        }
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.doi == "10.1234/test"

    def test_paper_type_from_work_type(self):
        """Paper type is derived from the work type field."""
        work = {"title": "A Paper", "type": "book-chapter"}
        paper = OpenAlexSearcher()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type == PaperType.INCOLLECTION


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
            "findpapers.searchers.base.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all(Database.OPENALEX in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, openalex_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = OpenAlexSearcher()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)

        with patch(
            "findpapers.searchers.base.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

    def test_http_error_breaks_loop(self, simple_query):
        """Exception in _get breaks the loop and returns what was gathered."""
        searcher = OpenAlexSearcher()

        with patch.object(searcher, "_get", side_effect=Exception("timeout")), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(self, simple_query, openalex_sample_json, mock_response):
        """Progress callback is called after processing results."""
        searcher = OpenAlexSearcher()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)
        callback = MagicMock()

        with patch(
            "findpapers.searchers.base.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = OpenAlexSearcher()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

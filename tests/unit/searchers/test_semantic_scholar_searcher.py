"""Unit tests for SemanticScholarSearcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.core.paper import PaperType
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder
from findpapers.searchers.semantic_scholar import (
    SemanticScholarSearcher,
    _semantic_scholar_types_to_paper_type,
)


class TestSemanticScholarTypesToPaperType:
    """Tests for _semantic_scholar_types_to_paper_type helper."""

    def test_none_returns_none(self):
        """None input returns None."""
        assert _semantic_scholar_types_to_paper_type(None) is None

    def test_empty_list_returns_none(self):
        """Empty list returns None."""
        assert _semantic_scholar_types_to_paper_type([]) is None

    def test_thesis_maps_to_phdthesis(self):
        """'Thesis' maps to PaperType.PHDTHESIS."""
        assert _semantic_scholar_types_to_paper_type(["Thesis"]) == PaperType.PHDTHESIS

    def test_booksection_maps_to_incollection(self):
        """'BookSection' maps to PaperType.INCOLLECTION."""
        assert _semantic_scholar_types_to_paper_type(["BookSection"]) == PaperType.INCOLLECTION

    def test_book_maps_to_inbook(self):
        """'Book' maps to PaperType.INBOOK."""
        assert _semantic_scholar_types_to_paper_type(["Book"]) == PaperType.INBOOK

    def test_conference_maps_to_inproceedings(self):
        """'Conference' maps to PaperType.INPROCEEDINGS."""
        assert _semantic_scholar_types_to_paper_type(["Conference"]) == PaperType.INPROCEEDINGS

    def test_journal_article_maps_to_article(self):
        """'JournalArticle' maps to PaperType.ARTICLE."""
        assert _semantic_scholar_types_to_paper_type(["JournalArticle"]) == PaperType.ARTICLE

    def test_review_maps_to_article(self):
        """'Review' maps to PaperType.ARTICLE."""
        assert _semantic_scholar_types_to_paper_type(["Review"]) == PaperType.ARTICLE

    def test_clinical_trial_maps_to_article(self):
        """'ClinicalTrial' maps to PaperType.ARTICLE."""
        assert _semantic_scholar_types_to_paper_type(["ClinicalTrial"]) == PaperType.ARTICLE

    def test_unknown_returns_none(self):
        """Unknown type returns None."""
        assert _semantic_scholar_types_to_paper_type(["Unknown"]) is None

    def test_priority_thesis_over_journal(self):
        """Thesis takes priority over JournalArticle when both present."""
        result = _semantic_scholar_types_to_paper_type(["JournalArticle", "Thesis"])
        assert result == PaperType.PHDTHESIS

    def test_case_insensitive(self):
        """Type matching is case-insensitive."""
        assert _semantic_scholar_types_to_paper_type(["thesis"]) == PaperType.PHDTHESIS


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

    def test_rate_interval_without_key(self):
        """Default rate interval used when no API key provided."""
        from findpapers.searchers.semantic_scholar import _MIN_REQUEST_INTERVAL_DEFAULT

        searcher = SemanticScholarSearcher()
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_DEFAULT

    def test_rate_interval_with_key(self):
        """Rate interval with key matches INTERVAL_WITH_KEY constant."""
        from findpapers.searchers.semantic_scholar import _MIN_REQUEST_INTERVAL_WITH_KEY

        searcher = SemanticScholarSearcher(api_key="key")
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_WITH_KEY


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

    def test_pdf_url_extracted(self):
        """openAccessPdf.url is extracted as pdf_url."""
        item = {
            "title": "A Paper",
            "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        }
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_keywords_from_fields_of_study(self):
        """fieldsOfStudy strings are collected as keywords."""
        item = {
            "title": "A Paper",
            "fieldsOfStudy": ["Computer Science", "Biology"],
        }
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.keywords is not None
        assert "Computer Science" in paper.keywords

    def test_publication_from_journal(self):
        """Publication is built from journal.name."""
        item = {
            "title": "A Paper",
            "journal": {"name": "Nature", "pages": "1-10"},
            "venue": "",
        }
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.publication is not None
        assert paper.publication.title == "Nature"
        assert paper.pages == "1-10"

    def test_publication_from_venue_fallback(self):
        """venue is used as publication title when journal.name is absent."""
        item = {
            "title": "A Paper",
            "journal": {},
            "venue": "ICML",
        }
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.publication is not None
        assert paper.publication.title == "ICML"

    def test_doi_from_external_ids(self):
        """DOI is extracted from externalIds.DOI."""
        item = {
            "title": "A Paper",
            "externalIds": {"DOI": "10.1234/test"},
        }
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.doi == "10.1234/test"

    def test_year_fallback_for_pub_date(self):
        """Year field is used as fallback when publicationDate is absent."""
        item = {"title": "A Paper", "year": 2020}
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.publication_date is not None
        assert paper.publication_date.year == 2020

    def test_paper_type_thesis(self):
        """publicationTypes with 'Thesis' maps to PHDTHESIS."""
        item = {"title": "A Thesis", "publicationTypes": ["Thesis"]}
        paper = SemanticScholarSearcher._parse_paper(item)
        assert paper is not None
        assert paper.paper_type == PaperType.PHDTHESIS


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

    def test_http_error_breaks_loop(self, simple_query):
        """Exception in _get breaks the loop and returns empty list."""
        searcher = SemanticScholarSearcher()

        with patch.object(searcher, "_get", side_effect=Exception("network error")), patch.object(
            searcher, "_rate_limit"
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(
        self,
        simple_query,
        semantic_scholar_sample_json,
        mock_response,
    ):
        """Progress callback is called after each page."""
        searcher = SemanticScholarSearcher()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)
        callback = MagicMock()

        with patch(
            "findpapers.searchers.semantic_scholar.requests.get",
            side_effect=[first_page, second_page],
        ), patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = SemanticScholarSearcher()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

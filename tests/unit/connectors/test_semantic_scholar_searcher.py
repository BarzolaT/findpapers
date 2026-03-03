"""Unit tests for SemanticScholarConnector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.connectors.semantic_scholar import SemanticScholarConnector
from findpapers.core.paper import PaperType
from findpapers.core.search_result import Database
from findpapers.core.source import SourceType
from findpapers.query.builders.semantic_scholar import SemanticScholarQueryBuilder


class TestSemanticScholarConnectorInit:
    """Tests for SemanticScholarConnector initialisation."""

    def test_default_builder_created(self):
        """Connector creates SemanticScholarQueryBuilder when none provided."""
        searcher = SemanticScholarConnector()
        assert isinstance(searcher.query_builder, SemanticScholarQueryBuilder)

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = SemanticScholarConnector(api_key="test_key")
        assert searcher._api_key == "test_key"

    def test_warning_when_no_api_key(self, caplog):
        """A warning is logged when no API key is provided."""
        import logging

        with caplog.at_level(logging.WARNING, logger="findpapers.connectors.semantic_scholar"):
            SemanticScholarConnector()
        assert any("No API key provided for Semantic Scholar" in msg for msg in caplog.messages)

    def test_no_warning_when_api_key_provided(self, caplog):
        """No warning is logged when an API key is provided."""
        import logging

        with caplog.at_level(logging.WARNING, logger="findpapers.connectors.semantic_scholar"):
            SemanticScholarConnector(api_key="key")
        assert not any("No API key provided" in msg for msg in caplog.messages)

    def test_name(self):
        """Connector name is 'Semantic Scholar'."""
        assert SemanticScholarConnector().name == Database.SEMANTIC_SCHOLAR

    def test_rate_interval_without_key(self):
        """Default rate interval used when no API key provided."""
        from findpapers.connectors.semantic_scholar import _MIN_REQUEST_INTERVAL_DEFAULT

        searcher = SemanticScholarConnector()
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_DEFAULT

    def test_rate_interval_with_key(self):
        """Rate interval with key matches INTERVAL_WITH_KEY constant."""
        from findpapers.connectors.semantic_scholar import _MIN_REQUEST_INTERVAL_WITH_KEY

        searcher = SemanticScholarConnector(api_key="key")
        assert searcher._request_interval == _MIN_REQUEST_INTERVAL_WITH_KEY


class TestSemanticScholarConnectorParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, semantic_scholar_sample_json):
        """Parsing sample data entries returns non-empty list of papers."""
        data = semantic_scholar_sample_json.get("data", [])
        assert len(data) > 0

        papers = [SemanticScholarConnector()._parse_paper(item) for item in data]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, semantic_scholar_sample_json):
        """Parsed paper has 'Semantic Scholar' in databases set."""
        item = semantic_scholar_sample_json["data"][0]
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert Database.SEMANTIC_SCHOLAR in paper.databases

    def test_missing_title_returns_none(self):
        """Item with blank title returns None."""
        paper = SemanticScholarConnector()._parse_paper({"title": "", "abstract": "a"})
        assert paper is None

    def test_pdf_url_extracted(self):
        """openAccessPdf.url is extracted as pdf_url."""
        item = {
            "title": "A Paper",
            "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_keywords_from_fields_of_study(self):
        """fieldsOfStudy strings are collected as keywords."""
        item = {
            "title": "A Paper",
            "fieldsOfStudy": ["Computer Science", "Biology"],
        }
        paper = SemanticScholarConnector()._parse_paper(item)
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
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "Nature"
        assert paper.page_range == "1-10"

    def test_publication_from_venue_fallback(self):
        """venue is used as publication title when journal.name is absent."""
        item = {
            "title": "A Paper",
            "journal": {},
            "venue": "ICML",
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "ICML"

    def test_source_type_from_publication_venue_journal(self):
        """publicationVenue.type 'journal' maps to SourceType.JOURNAL."""
        item = {
            "title": "A Paper",
            "journal": {"name": "Nature"},
            "publicationVenue": {"type": "journal"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.JOURNAL

    def test_source_type_from_publication_venue_conference(self):
        """publicationVenue.type 'conference' maps to SourceType.CONFERENCE."""
        item = {
            "title": "A Paper",
            "journal": {"name": "NeurIPS"},
            "publicationVenue": {"type": "conference"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.CONFERENCE

    def test_source_type_fallback_to_publication_types(self):
        """publicationTypes list is used when publicationVenue is absent."""
        item = {
            "title": "A Paper",
            "journal": {"name": "Some Journal"},
            "publicationTypes": ["JournalArticle"],
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.JOURNAL

    def test_source_type_conference_from_publication_types(self):
        """publicationTypes 'Conference' maps to SourceType.CONFERENCE."""
        item = {
            "title": "A Paper",
            "journal": {"name": "Workshop"},
            "publicationTypes": ["Conference"],
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.CONFERENCE

    def test_source_type_none_when_no_venue_or_types(self):
        """source_type is None when neither publicationVenue nor publicationTypes is present."""
        item = {
            "title": "A Paper",
            "journal": {"name": "Unknown"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type is None

    def test_doi_from_external_ids(self):
        """DOI is extracted from externalIds.DOI."""
        item = {
            "title": "A Paper",
            "externalIds": {"DOI": "10.1234/test"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.doi == "10.1234/test"

    def test_doi_derived_from_arxiv_id_when_doi_absent(self):
        """DOI is derived from ArXivId when externalIds.DOI is absent."""
        item = {
            "title": "A Paper",
            "externalIds": {"ArXivId": "1706.03762"},
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.doi == "10.48550/arXiv.1706.03762"

    def test_explicit_doi_takes_priority_over_arxiv_id(self):
        """externalIds.DOI takes priority over ArXivId derivation."""
        item = {
            "title": "A Paper",
            "externalIds": {
                "DOI": "10.1145/3531146.3533206",
                "ArXivId": "2301.12345",
            },
        }
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.doi == "10.1145/3531146.3533206"

    def test_doi_none_when_no_external_ids(self):
        """DOI is None when externalIds has neither DOI nor ArXivId."""
        item = {"title": "A Paper", "externalIds": {}}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.doi is None

    def test_year_fallback_for_pub_date(self):
        """Year field is used as fallback when publicationDate is absent."""
        item = {"title": "A Paper", "year": 2020}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.publication_date is not None
        assert paper.publication_date.year == 2020

    def test_paper_type_article_from_journal_article(self):
        """publicationTypes 'JournalArticle' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["JournalArticle"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_case_report(self):
        """publicationTypes 'CaseReport' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["CaseReport"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_clinical_trial(self):
        """publicationTypes 'ClinicalTrial' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["ClinicalTrial"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_editorial(self):
        """publicationTypes 'Editorial' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["Editorial"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_letters_and_comments(self):
        """publicationTypes 'LettersAndComments' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["LettersAndComments"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_meta_analysis(self):
        """publicationTypes 'MetaAnalysis' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["MetaAnalysis"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_article_from_study(self):
        """publicationTypes 'Study' maps to PaperType.ARTICLE."""
        item = {"title": "P", "publicationTypes": ["Study"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_inproceedings_from_conference(self):
        """publicationTypes 'Conference' maps to PaperType.INPROCEEDINGS."""
        item = {"title": "P", "publicationTypes": ["Conference"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_book_from_book(self):
        """publicationTypes 'Book' maps to PaperType.BOOK."""
        item = {"title": "P", "publicationTypes": ["Book"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.BOOK

    def test_paper_type_inbook_from_book_section(self):
        """publicationTypes 'BookSection' maps to PaperType.INBOOK."""
        item = {"title": "P", "publicationTypes": ["BookSection"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.INBOOK

    def test_paper_type_misc_from_dataset(self):
        """publicationTypes 'Dataset' maps to PaperType.MISC."""
        item = {"title": "P", "publicationTypes": ["Dataset"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.MISC

    def test_paper_type_misc_from_news(self):
        """publicationTypes 'News' maps to PaperType.MISC."""
        item = {"title": "P", "publicationTypes": ["News"]}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is PaperType.MISC

    def test_paper_type_none_when_missing(self):
        """Missing publicationTypes results in paper_type being None."""
        item = {"title": "P"}
        paper = SemanticScholarConnector()._parse_paper(item)
        assert paper is not None
        assert paper.paper_type is None


class TestSemanticScholarConnectorSearch:
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
        searcher = SemanticScholarConnector()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all(Database.SEMANTIC_SCHOLAR in p.databases for p in papers)

    def test_max_papers_respected(
        self,
        simple_query,
        semantic_scholar_sample_json,
        mock_response,
    ):
        """search() returns no more than max_papers papers."""
        searcher = SemanticScholarConnector()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

    def test_http_error_breaks_loop(self, simple_query):
        """Exception in _get breaks the loop and returns empty list."""
        searcher = SemanticScholarConnector()

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
        searcher = SemanticScholarConnector()
        first_page = mock_response(json_data=semantic_scholar_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._empty_page(mock_response)
        callback = MagicMock()

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = SemanticScholarConnector()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

"""Unit tests for OpenAlexConnector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.connectors.openalex import (
    OpenAlexConnector,
    _reconstruct_abstract,
)
from findpapers.core.paper import PaperType
from findpapers.core.search_result import Database
from findpapers.core.source import SourceType
from findpapers.query.builders.openalex import OpenAlexQueryBuilder


class TestOpenAlexConnectorInit:
    """Tests for OpenAlexConnector initialisation."""

    def test_default_builder_created(self):
        """Connector creates OpenAlexQueryBuilder when none provided."""
        searcher = OpenAlexConnector()
        assert isinstance(searcher.query_builder, OpenAlexQueryBuilder)

    def test_email_stored(self):
        """Email is stored for polite pool requests."""
        searcher = OpenAlexConnector(email="test@example.com")
        assert searcher._email == "test@example.com"

    def test_name(self):
        """Connector name is 'OpenAlex'."""
        assert OpenAlexConnector().name == Database.OPENALEX

    def test_api_key_stored(self):
        """API key is stored on the instance."""
        searcher = OpenAlexConnector(api_key="mykey")
        assert searcher._api_key == "mykey"

    def test_warning_when_no_api_key(self, caplog):
        """A warning is logged when no API key is provided."""
        import logging

        with caplog.at_level(logging.WARNING, logger="findpapers.connectors.openalex"):
            OpenAlexConnector()
        assert any("No API key provided for OpenAlex" in msg for msg in caplog.messages)

    def test_no_warning_when_api_key_provided(self, caplog):
        """No warning is logged when an API key is provided."""
        import logging

        with caplog.at_level(logging.WARNING, logger="findpapers.connectors.openalex"):
            OpenAlexConnector(api_key="mykey")
        assert not any("No API key provided" in msg for msg in caplog.messages)


class TestOpenAlexPrepareHeaders:
    """Tests for _prepare_headers."""

    def test_default_user_agent(self):
        """Without email, default User-Agent is used."""
        headers = OpenAlexConnector()._prepare_headers({})
        assert "findpapers" in headers["User-Agent"]

    def test_custom_user_agent_with_email(self):
        """With email, User-Agent contains the email address."""
        headers = OpenAlexConnector(email="me@example.com")._prepare_headers({})
        assert "me@example.com" in headers["User-Agent"]


class TestOpenAlexConnectorParsePaper:
    """Tests for _parse_paper."""

    def test_parse_sample_json(self, openalex_sample_json):
        """Parsing sample JSON results returns non-empty list of papers."""
        results = openalex_sample_json.get("results", [])
        assert len(results) > 0

        papers = [OpenAlexConnector()._parse_paper(r) for r in results]
        valid = [p for p in papers if p is not None]
        assert len(valid) > 0

    def test_paper_has_database_tag(self, openalex_sample_json):
        """Parsed paper has 'OpenAlex' in databases set."""
        result = openalex_sample_json["results"][0]
        paper = OpenAlexConnector()._parse_paper(result)
        assert paper is not None
        assert Database.OPENALEX in paper.databases

    def test_missing_title_returns_none(self):
        """Result with blank title returns None."""
        paper = OpenAlexConnector()._parse_paper({"title": "  "})
        assert paper is None

    def test_open_access_url_used(self):
        """oa_url from open_access is used as paper URL."""
        work = {
            "title": "A Paper",
            "open_access": {"oa_url": "https://example.com/paper.pdf"},
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.url == "https://example.com/paper.pdf"

    def test_landing_page_url_fallback(self):
        """primary_location.landing_page_url is fallback when oa_url absent."""
        work = {
            "title": "A Paper",
            "open_access": {},
            "primary_location": {"landing_page_url": "https://example.com/landing"},
        }
        paper = OpenAlexConnector()._parse_paper(work)
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
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_keywords_from_concepts_and_keywords(self):
        """Keywords collected from both concepts and keywords fields."""
        work = {
            "title": "A Paper",
            "concepts": [{"display_name": "Machine Learning"}],
            "keywords": [{"display_name": "Deep Learning"}],
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.keywords is not None
        assert "Machine Learning" in paper.keywords
        assert "Deep Learning" in paper.keywords

    def test_source_from_primary_location(self):
        """Source is built from primary_location.source when it is a journal."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {
                    "display_name": "Nature",
                    "issn_l": ["1234-5678"],
                    "type": "journal",
                },
                "landing_page_url": None,
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "Nature"
        assert paper.source.issn == "1234-5678"

    def test_source_skipped_when_repository(self):
        """Repository-only sources should produce a repository-type source."""
        work = {
            "title": "A Dissertation",
            "primary_location": {
                "source": {
                    "display_name": "University of Liverpool",
                    "type": "repository",
                },
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "University of Liverpool"
        assert paper.source.source_type == SourceType.REPOSITORY

    def test_source_prefers_journal_over_repository(self):
        """When primary location is a repository, journal from other locations is used."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {
                    "display_name": "Zenodo",
                    "type": "repository",
                },
            },
            "locations": [
                {
                    "source": {
                        "display_name": "Zenodo",
                        "type": "repository",
                    },
                },
                {
                    "source": {
                        "display_name": "Nature Physics",
                        "issn_l": ["1745-2473"],
                        "type": "journal",
                    },
                },
            ],
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "Nature Physics"
        assert paper.source.source_type == SourceType.JOURNAL

    def test_source_type_conference(self):
        """Conference source type is mapped to SourceType.CONFERENCE."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {
                    "display_name": "NeurIPS",
                    "type": "conference",
                },
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.CONFERENCE

    def test_source_type_book_series(self):
        """'book series' source type is mapped to SourceType.BOOK."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {
                    "display_name": "Lecture Notes in CS",
                    "type": "book series",
                },
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.BOOK

    def test_source_type_ebook_platform(self):
        """'ebook platform' source type is mapped to SourceType.BOOK."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {
                    "display_name": "Springer eBooks",
                    "type": "ebook platform",
                },
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.source_type == SourceType.BOOK

    def test_source_without_type_is_accepted(self):
        """Sources without a type field are accepted (fallback)."""
        work = {
            "title": "A Paper",
            "primary_location": {
                "source": {"display_name": "Nature", "issn_l": ["1234-5678"]},
                "landing_page_url": None,
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.source is not None
        assert paper.source.title == "Nature"

    def test_doi_stripped_of_prefix(self):
        """DOI prefix 'https://doi.org/' is stripped."""
        work = {
            "title": "A Paper",
            "doi": "https://doi.org/10.1234/test",
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.doi == "10.1234/test"

    def test_pages_from_biblio(self):
        """Pages are extracted from biblio.first_page and last_page."""
        work = {
            "title": "A Paper",
            "biblio": {"first_page": "100", "last_page": "115"},
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.page_range == "100\u2013115"

    def test_pages_first_only(self):
        """Only first_page is stored when last_page is absent."""
        work = {
            "title": "A Paper",
            "biblio": {"first_page": "42", "last_page": None},
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.page_range == "42"

    def test_pages_none_when_biblio_absent(self):
        """Pages are None when biblio is not present."""
        work = {"title": "A Paper"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.page_range is None

    def test_pages_from_sample_data(self, openalex_sample_json):
        """Pages are extracted from real sample data."""
        results = openalex_sample_json["results"]
        paper = OpenAlexConnector()._parse_paper(results[0])
        assert paper is not None
        assert paper.page_range is not None
        assert "\u2013" in paper.page_range  # en-dash separator

    def test_paper_type_article_from_work_type(self):
        """work.type 'article' maps to PaperType.ARTICLE."""
        work = {"title": "P", "type": "article"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.ARTICLE

    def test_paper_type_book_chapter(self):
        """work.type 'book-chapter' maps to PaperType.INBOOK."""
        work = {"title": "P", "type": "book-chapter"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.INBOOK

    def test_paper_type_dissertation(self):
        """work.type 'dissertation' maps to PaperType.PHDTHESIS."""
        work = {"title": "P", "type": "dissertation"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.PHDTHESIS

    def test_paper_type_preprint(self):
        """work.type 'preprint' maps to PaperType.UNPUBLISHED."""
        work = {"title": "P", "type": "preprint"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.UNPUBLISHED

    def test_paper_type_report(self):
        """work.type 'report' maps to PaperType.TECHREPORT."""
        work = {"title": "P", "type": "report"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.TECHREPORT

    def test_paper_type_book(self):
        """work.type 'book' maps to PaperType.BOOK."""
        work = {"title": "P", "type": "book"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.BOOK

    def test_paper_type_inproceedings_when_article_in_conference_source(self):
        """work.type 'article' with conference source promotes to INPROCEEDINGS."""
        work = {
            "title": "P",
            "type": "article",
            "primary_location": {
                "source": {
                    "display_name": "NeurIPS 2023",
                    "type": "conference",
                },
            },
        }
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is PaperType.INPROCEEDINGS

    def test_paper_type_none_when_unknown(self):
        """Unknown work.type results in paper_type being None."""
        work = {"title": "P", "type": "unknownxyz"}
        paper = OpenAlexConnector()._parse_paper(work)
        assert paper is not None
        assert paper.paper_type is None


class TestOpenAlexConnectorReconstructAbstract:
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


class TestOpenAlexConnectorSearch:
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
        searcher = OpenAlexConnector()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query)

        assert len(papers) > 0
        assert all(Database.OPENALEX in p.databases for p in papers)

    def test_max_papers_respected(self, simple_query, openalex_sample_json, mock_response):
        """search() returns no more than max_papers papers."""
        searcher = OpenAlexConnector()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(simple_query, max_papers=2)

        assert len(papers) <= 2

    def test_http_error_breaks_loop(self, simple_query):
        """Exception in _get breaks the loop and returns what was gathered."""
        searcher = OpenAlexConnector()

        with (
            patch.object(searcher, "_get", side_effect=Exception("timeout")),
            patch.object(searcher, "_rate_limit"),
        ):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_progress_callback_called(self, simple_query, openalex_sample_json, mock_response):
        """Progress callback is called after processing results."""
        searcher = OpenAlexConnector()
        first_page = mock_response(json_data=openalex_sample_json)
        first_page.raise_for_status = MagicMock()
        second_page = self._make_next_page_response(mock_response)
        callback = MagicMock()

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [first_page, second_page]
        with patch.object(searcher, "_rate_limit"):
            searcher.search(simple_query, progress_callback=callback)

        callback.assert_called()

    def test_search_raises_surfaces_via_base(self, simple_query):
        """Unexpected exception in _fetch_papers returns an empty list."""
        searcher = OpenAlexConnector()

        with patch.object(searcher, "_fetch_papers", side_effect=RuntimeError("boom")):
            papers = searcher.search(simple_query)

        assert papers == []

    def test_or_query_fetches_all_expansion_branches(self, or_query, mock_response):
        """Each OR clause is queried even when the first clause fills the budget.

        When an OR query is expanded into two sub-queries (one per clause),
        both HTTP requests must be issued.  Each branch uses an independent
        accumulator so that one clause cannot exhaust max_papers and prevent
        the remaining clauses from being fetched.
        """
        searcher = OpenAlexConnector()

        def _make_page(doi: str, title: str) -> MagicMock:
            data = {
                "meta": {"count": 1, "per_page": 1, "next_cursor": None},
                "results": [
                    {
                        "title": title,
                        "doi": f"https://doi.org/{doi}",
                        "publication_date": "2024-01-01",
                        "abstract_inverted_index": None,
                        "authorships": [],
                        "cited_by_count": 0,
                        "open_access": {},
                        "locations": [],
                        "primary_location": {},
                        "concepts": [],
                        "keywords": [],
                        "type": "article",
                    }
                ],
            }
            r = mock_response(json_data=data)
            r.raise_for_status = MagicMock()
            return r

        page_ml = _make_page("10.ml/1", "Machine Learning Paper")
        page_dl = _make_page("10.dl/1", "Deep Learning Paper")

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [page_ml, page_dl]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(or_query, max_papers=2)

        # Both OR clauses must have been fetched.
        assert len(papers) == 2
        dois = {p.doi for p in papers}
        assert "10.ml/1" in dois
        assert "10.dl/1" in dois

    def test_or_query_max_papers_still_respected(self, or_query, mock_response):
        """Final result is capped at max_papers even when OR expands to multiple clauses."""
        searcher = OpenAlexConnector()

        def _make_page(doi: str, title: str) -> MagicMock:
            data = {
                "meta": {"count": 1, "per_page": 1, "next_cursor": None},
                "results": [
                    {
                        "title": title,
                        "doi": f"https://doi.org/{doi}",
                        "publication_date": "2024-01-01",
                        "abstract_inverted_index": None,
                        "authorships": [],
                        "cited_by_count": 0,
                        "open_access": {},
                        "locations": [],
                        "primary_location": {},
                        "concepts": [],
                        "keywords": [],
                        "type": "article",
                    }
                ],
            }
            r = mock_response(json_data=data)
            r.raise_for_status = MagicMock()
            return r

        page_ml = _make_page("10.ml/1", "Machine Learning Paper")
        page_dl = _make_page("10.dl/1", "Deep Learning Paper")

        searcher._http_session = MagicMock()
        searcher._http_session.get.side_effect = [page_ml, page_dl]
        with patch.object(searcher, "_rate_limit"):
            papers = searcher.search(or_query, max_papers=1)

        assert len(papers) <= 1

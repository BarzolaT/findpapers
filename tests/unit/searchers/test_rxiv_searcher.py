"""Unit tests for RxivSearcher (shared bioRxiv / medRxiv base)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from findpapers.query.builders.rxiv import RxivQueryBuilder
from findpapers.searchers.biorxiv import BiorxivSearcher
from findpapers.searchers.rxiv import RxivSearcher


def _make_searcher() -> BiorxivSearcher:
    """Return a concrete RxivSearcher subclass for testing the shared base."""
    return BiorxivSearcher()


class TestRxivSearcherInit:
    """Tests for RxivSearcher.__init__."""

    def test_default_builder_created(self):
        """Default RxivQueryBuilder is created when none provided."""
        searcher = _make_searcher()
        assert isinstance(searcher.query_builder, RxivQueryBuilder)

    def test_custom_builder_used(self):
        """Custom builder is stored when provided."""
        builder = RxivQueryBuilder()
        searcher = BiorxivSearcher(query_builder=builder)
        assert searcher.query_builder is builder

    def test_rxiv_server_stored(self):
        """Server name is stored on _rxiv_server."""
        searcher = _make_searcher()
        assert searcher._rxiv_server == "biorxiv"


class TestRxivSearcherName:
    """Tests for the 'name' property (provided by subclasses)."""

    def test_searcher_is_available_by_default(self):
        """is_available returns True (no API key required)."""
        assert _make_searcher().is_available is True

    def test_name(self):
        """BiorxivSearcher name is 'bioRxiv'."""
        assert _make_searcher().name == "bioRxiv"


class TestRxivSearcherBuildSearchUrl:
    """Tests for _build_search_url."""

    def test_url_contains_encoded_terms(self):
        """URL contains percent-encoded search terms."""
        searcher = _make_searcher()
        params = {"terms": ["machine learning"], "match": "match-all"}
        url = searcher._build_search_url(params, page=0)
        assert "machine" in url

    def test_url_contains_jcode(self):
        """URL contains the journal code."""
        searcher = _make_searcher()
        params = {"terms": ["deep"], "match": "match-all"}
        url = searcher._build_search_url(params, page=0)
        assert "biorxiv" in url

    def test_page_offset_applied(self):
        """Page offset is applied correctly (page 1 gives cursor 10)."""
        searcher = _make_searcher()
        params = {"terms": ["deep"], "match": "match-all"}
        url_page0 = searcher._build_search_url(params, page=0)
        url_page1 = searcher._build_search_url(params, page=1)
        assert "cursor%3A0" in url_page0
        assert "cursor%3A10" in url_page1


class TestRxivSearcherParseTotalFromSoup:
    """Tests for _parse_total_from_soup."""

    def test_returns_none_when_no_matching_element(self):
        """Returns None when page has no known result-count elements."""
        soup = BeautifulSoup("<html><body><p>No results section</p></body></html>", "html.parser")
        assert RxivSearcher._parse_total_from_soup(soup) is None

    def test_parses_real_biorxiv_structure(self):
        """Parses total from the real bioRxiv h1#page-title inside .highwire-search-summary."""
        html = """
        <div class="highwire-search-summary" id="search-summary-wrapper">
            <h1 id="page-title">26,467 Results</h1>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert RxivSearcher._parse_total_from_soup(soup) == 26467

    def test_parses_total_without_comma(self):
        """Parses total when the number has no thousands separator."""
        html = """
        <div class="highwire-search-summary" id="search-summary-wrapper">
            <h1 id="page-title">42 Results</h1>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert RxivSearcher._parse_total_from_soup(soup) == 42

    def test_returns_none_when_h1_not_inside_summary(self):
        """Returns None when h1#page-title exists but not inside .highwire-search-summary."""
        html = "<h1 id='page-title'>Some other heading</h1>"
        soup = BeautifulSoup(html, "html.parser")
        assert RxivSearcher._parse_total_from_soup(soup) is None

    def test_returns_none_when_h1_has_no_digits(self):
        """Returns None when the h1 text contains no parseable number."""
        html = """
        <div class="highwire-search-summary">
            <h1 id="page-title">No results found</h1>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert RxivSearcher._parse_total_from_soup(soup) is None


class TestRxivSearcherScrapeDois:
    """Tests for _scrape_dois."""

    def test_returns_dois_from_html(self, mock_response):
        """DOIs are extracted from anchor tags."""
        html = """<html><body>
            <a class="highwire-cite-linked-title" href="/content/10.1101/2021.01.01.123456v1">Paper</a>
            <a class="highwire-cite-linked-title" href="/content/10.1101/2021.02.02.654321v2">Paper2</a>
        </body></html>"""
        searcher = _make_searcher()
        response = mock_response(text=html)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, total = searcher._scrape_dois("https://example.com/search")

        assert len(dois) == 2
        assert "10.1101/2021.01.01.123456v1" in dois
        assert total is None  # No result-count element in this HTML

    def test_returns_empty_on_http_error(self):
        """Empty list and None total are returned when HTTP request fails."""
        searcher = _make_searcher()

        with patch.object(searcher, "_get", side_effect=Exception("network error")):
            dois, total = searcher._scrape_dois("https://example.com/search")

        assert dois == []
        assert total is None

    def test_returns_empty_when_no_anchors(self, mock_response):
        """Empty list returned when page has no matching anchor elements."""
        searcher = _make_searcher()
        response = mock_response(text="<html><body><p>No results</p></body></html>")
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, total = searcher._scrape_dois("https://example.com/search")

        assert dois == []
        assert total is None

    def test_handles_href_as_list(self, mock_response):
        """Handles cases where BeautifulSoup returns href as a list."""
        html = """<html><body>
            <a class="highwire-cite-linked-title" href="/content/10.1101/2021.03.03.111v1">X</a>
        </body></html>"""
        searcher = _make_searcher()
        response = mock_response(text=html)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, _total = searcher._scrape_dois("https://example.com")

        assert len(dois) >= 1

    def test_handles_absolute_url_href(self, mock_response):
        """Absolute href URLs are normalised to bare DOIs correctly."""
        html = """<html><body>
            <a class="highwire-cite-linked-title"
               href="https://www.biorxiv.org/content/10.1101/2025.10.31.685841v1">Paper</a>
        </body></html>"""
        searcher = _make_searcher()
        response = mock_response(text=html)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, _total = searcher._scrape_dois("https://example.com/search")

        assert len(dois) == 1
        assert dois[0] == "10.1101/2025.10.31.685841v1"

    def test_handles_early_path_format(self, mock_response):
        """New biorxiv path format /content/early/YYYY/MM/DD/SUFFIX is handled."""
        html = """<html><body>
            <a class="highwire-cite-linked-title"
               href="/content/early/2026/02/19/2025.10.31.685841v1">Paper A</a>
            <a class="highwire-cite-linked-title"
               href="https://biorxiv.org/content/early/2026/01/15/2025.03.18.644029">Paper B</a>
        </body></html>"""
        searcher = _make_searcher()
        response = mock_response(text=html)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, _total = searcher._scrape_dois("https://example.com/search")

        assert len(dois) == 2
        assert "10.1101/2025.10.31.685841v1" in dois
        assert "10.1101/2025.03.18.644029" in dois

    def test_returns_total_when_present(self, mock_response):
        """Total count is returned when the real bioRxiv result-count element is present."""
        html = """<html><body>
            <div class="highwire-search-summary" id="search-summary-wrapper">
                <h1 id="page-title">999 Results</h1>
            </div>
            <a class="highwire-cite-linked-title" href="/content/10.1101/2021.01.01.111v1">P</a>
        </body></html>"""
        searcher = _make_searcher()
        response = mock_response(text=html)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            dois, total = searcher._scrape_dois("https://example.com/search")

        assert len(dois) == 1
        assert total == 999


class TestRxivSearcherFetchMetadata:
    """Tests for _fetch_metadata."""

    def test_returns_first_collection_item(self, mock_response):
        """Returns the first item from the collection."""
        data = {"collection": [{"title": "Test Paper", "doi": "10.1101/abc"}]}
        searcher = _make_searcher()
        response = mock_response(json_data=data)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            meta = searcher._fetch_metadata("10.1101/abc")

        assert meta is not None
        assert meta["title"] == "Test Paper"

    def test_returns_none_on_empty_collection(self, mock_response):
        """Returns None when collection is empty."""
        data = {"collection": []}
        searcher = _make_searcher()
        response = mock_response(json_data=data)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            meta = searcher._fetch_metadata("10.1101/missing")

        assert meta is None

    def test_returns_none_on_http_error(self):
        """Returns None when the HTTP request fails."""
        searcher = _make_searcher()

        with patch.object(searcher, "_get", side_effect=Exception("timeout")):
            meta = searcher._fetch_metadata("10.1101/fail")

        assert meta is None

    def test_warns_on_doi_not_recognizable(self, mock_response, caplog):
        """Logs a warning when the API reports 'DOI not recognizable'."""
        import logging

        data = {
            "messages": [{"status": "DOI not recognizable"}],
            "collection": [],
        }
        searcher = _make_searcher()
        response = mock_response(json_data=data)
        response.raise_for_status = MagicMock()

        with patch.object(searcher, "_get", return_value=response):
            with caplog.at_level(logging.WARNING, logger="findpapers.searchers.rxiv"):
                meta = searcher._fetch_metadata("10.64898/2026.02.17.12345678v1")

        assert meta is None
        assert any("DOI not recognizable" in r.message for r in caplog.records)


class TestRxivSearcherParsePaper:
    """Tests for _parse_paper."""

    def test_full_metadata_parses_correctly(self):
        """A complete metadata dict produces a valid Paper."""
        meta = {
            "title": "Advances in Deep Learning",
            "abstract": "We study deep learning models.",
            "doi": "10.1101/2021.01.01.123456",
            "authors": "Smith J; Doe A",
            "date": "2021-01-01",
            "category": "Computer Science",
        }
        paper = RxivSearcher._parse_paper(meta, "biorxiv")
        assert paper is not None
        assert paper.title == "Advances in Deep Learning"
        assert "biorxiv" in paper.databases
        assert paper.doi == "10.1101/2021.01.01.123456"
        assert len(paper.authors) == 2

    def test_missing_title_returns_none(self):
        """Returns None when title is absent."""
        paper = RxivSearcher._parse_paper({"title": "", "abstract": "text"}, "biorxiv")
        assert paper is None

    def test_no_doi_means_no_url(self):
        """Paper without DOI has no URL or PDF URL."""
        meta = {"title": "A Paper", "abstract": "", "doi": "", "authors": ""}
        paper = RxivSearcher._parse_paper(meta, "biorxiv")
        assert paper is not None
        assert paper.url is None
        assert paper.pdf_url is None

    def test_no_category_means_no_publication(self):
        """Paper without category has no Publication."""
        meta = {"title": "A Paper", "doi": "10.1101/x", "category": ""}
        paper = RxivSearcher._parse_paper(meta, "biorxiv")
        assert paper is not None
        assert paper.publication is None

    def test_invalid_date_is_ignored(self):
        """Malformed date string is silently ignored."""
        meta = {"title": "A Paper", "doi": "10.1101/x", "date": "not-a-date"}
        paper = RxivSearcher._parse_paper(meta, "biorxiv")
        assert paper is not None
        assert paper.publication_date is None

    def test_authors_semicolon_split(self):
        """Authors separated by semicolons are split correctly."""
        meta = {"title": "A", "authors": "Alpha B; Gamma D; Epsilon F"}
        paper = RxivSearcher._parse_paper(meta, "biorxiv")
        assert paper is not None
        assert len(paper.authors) == 3


class TestRxivSearcherSearchSingle:
    """Tests for _search_single."""

    def test_stops_when_max_papers_reached(self, mock_response):
        """Search stops when the max_papers limit is already met."""
        searcher = _make_searcher()
        papers: list = []  # already at limit simulation done via max_papers=0

        # max_papers=0: should not call _scrape_dois at all
        with patch.object(searcher, "_scrape_dois") as mock_scrape:
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=0,
                papers=papers,
                progress_callback=None,
            )
        mock_scrape.assert_not_called()

    def test_stops_when_scrape_returns_empty(self, mock_response):
        """Search loop stops when no DOIs are returned."""
        searcher = _make_searcher()
        papers: list = []

        with patch.object(searcher, "_scrape_dois", return_value=([], None)):
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=None,
                papers=papers,
                progress_callback=None,
            )

        assert papers == []

    def test_calls_progress_callback(self):
        """progress_callback is invoked for each DOI processed."""
        searcher = _make_searcher()
        papers: list = []
        callback = MagicMock()

        meta = {"title": "Paper A", "doi": "10.1101/a", "authors": "X Y"}

        with patch.object(
            searcher, "_scrape_dois", side_effect=[(["10.1101/a"], None), ([], None)]
        ), patch.object(searcher, "_fetch_metadata", return_value=meta):
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=None,
                papers=papers,
                progress_callback=callback,
            )

        callback.assert_called()
        # When max_papers is None and page provides no total, callback receives None.
        callback.assert_called_with(1, None)

    def test_calls_progress_callback_with_real_total(self):
        """progress_callback receives the real total scraped from the page."""
        searcher = _make_searcher()
        papers: list = []
        callback = MagicMock()

        meta = {"title": "Paper A", "doi": "10.1101/a", "authors": "X Y"}

        with patch.object(
            searcher, "_scrape_dois", side_effect=[(["10.1101/a"], 42), ([], None)]
        ), patch.object(searcher, "_fetch_metadata", return_value=meta):
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=10,
                papers=papers,
                progress_callback=callback,
            )

        # The real total (42) from the page must be used, not max_papers (10).
        callback.assert_called_with(1, 42)

    def test_calls_progress_callback_with_none_when_total_unavailable(self):
        """progress_callback receives None as total when page gives no count."""
        searcher = _make_searcher()
        papers: list = []
        callback = MagicMock()

        meta = {"title": "Paper A", "doi": "10.1101/a", "authors": "X Y"}

        with patch.object(
            searcher, "_scrape_dois", side_effect=[(["10.1101/a"], None), ([], None)]
        ), patch.object(searcher, "_fetch_metadata", return_value=meta):
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=10,
                papers=papers,
                progress_callback=callback,
            )

        # No total available from page — callback must receive None, not max_papers.
        callback.assert_called_with(1, None)

    def test_pagination_stops_when_fewer_than_10_dois(self):
        """Pagination stops when a page returns fewer than 10 DOIs."""
        searcher = _make_searcher()
        papers: list = []

        meta = {"title": "Paper", "doi": "10.1101/x", "authors": "A B"}
        with patch.object(
            searcher, "_scrape_dois", return_value=(["10.1101/x"], None)
        ), patch.object(searcher, "_fetch_metadata", return_value=meta):
            searcher._search_single(
                {"terms": ["x"], "match": "match-all"},
                max_papers=None,
                papers=papers,
                progress_callback=None,
            )

        # Only 1 DOI returned (< 10), so no second page should be requested
        assert len(papers) == 1


class TestRxivSearcherFetchPapers:
    """Tests for _fetch_papers and warning for large expansions."""

    def test_warning_logged_for_large_expansion(self, simple_query, caplog):
        """Warning is logged when expanded query exceeds threshold."""
        import logging

        from findpapers.searchers.base import QUERY_COMBINATIONS_WARNING_THRESHOLD

        searcher = _make_searcher()
        big_expansion = [simple_query] * (QUERY_COMBINATIONS_WARNING_THRESHOLD + 1)

        with patch.object(
            searcher._query_builder, "expand_query", return_value=big_expansion
        ), patch.object(searcher, "_search_single"), caplog.at_level(
            logging.WARNING, logger="findpapers.searchers.rxiv"
        ):
            searcher._fetch_papers(simple_query, max_papers=None, progress_callback=None)

        assert any("combination" in rec.message.lower() for rec in caplog.records)

    def test_deduplication_by_doi(self, simple_query):
        """Duplicate DOIs across expanded queries are removed."""
        searcher = _make_searcher()
        meta = {"title": "Paper", "doi": "10.1101/dup", "authors": "A B"}

        # Two expansions that each return the same DOI
        with patch.object(
            searcher._query_builder,
            "expand_query",
            return_value=[simple_query, simple_query],
        ), patch.object(
            searcher._query_builder,
            "convert_query",
            return_value={"terms": ["x"], "match": "match-all"},
        ), patch.object(
            searcher,
            "_scrape_dois",
            side_effect=[(["10.1101/dup"], None), ([], None), (["10.1101/dup"], None), ([], None)],
        ), patch.object(
            searcher, "_fetch_metadata", return_value=meta
        ):
            papers = searcher._fetch_papers(simple_query, max_papers=None, progress_callback=None)

        # Even though the DOI appears in both expansions, it should only appear once
        assert len(papers) == 1

    def test_stops_early_when_max_reached_across_expansions(self, simple_query):
        """Second expansion is skipped when max_papers is satisfied after first."""
        searcher = _make_searcher()
        meta = {"title": "Paper", "doi": "10.1101/p1", "authors": "A"}

        call_count = [0]

        def _search_single(params, max_papers, papers, progress_callback):
            if call_count[0] == 0:
                from findpapers.searchers.rxiv import RxivSearcher as R

                p = R._parse_paper(meta, "biorxiv")
                if p:
                    papers.append(p)
            call_count[0] += 1

        with patch.object(
            searcher._query_builder,
            "expand_query",
            return_value=[simple_query, simple_query],
        ), patch.object(
            searcher._query_builder,
            "convert_query",
            return_value={"terms": ["x"], "match": "match-all"},
        ), patch.object(
            searcher, "_search_single", side_effect=_search_single
        ):
            papers = searcher._fetch_papers(simple_query, max_papers=1, progress_callback=None)

        assert len(papers) <= 1
        # Second expansion should have been skipped
        assert call_count[0] == 1

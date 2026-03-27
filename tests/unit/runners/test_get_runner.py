"""Unit tests for GetRunner."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source
from findpapers.exceptions import InvalidParameterError
from findpapers.runners.get_runner import GetRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_paper(
    title: str = "Fake Paper Title",
    doi: str | None = "10.1234/test",
    url: str | None = None,
    keywords: set[str] | None = None,
    databases: set[str] | None = None,
) -> Paper:
    """Return a minimal Paper for use in tests."""
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=[Author(name="Alice Smith")],
        source=Source(title="Fake Journal"),
        publication_date=datetime.date(2023, 6, 15),
        doi=doi,
        url=url,
        keywords=keywords,
        databases=databases or {"crossref"},
    )


def _fake_crossref_work() -> dict:
    """Return a minimal CrossRef work record for testing."""
    return {
        "DOI": "10.1234/test",
        "title": ["Fake Paper Title"],
        "abstract": "<jats:p>An abstract.</jats:p>",
        "author": [{"given": "Alice", "family": "Smith", "affiliation": []}],
        "published-print": {"date-parts": [[2023, 6, 15]]},
        "container-title": ["Fake Journal"],
        "type": "journal-article",
        "is-referenced-by-count": 42,
    }


def _noop_fetch_doi(*_args, **_kwargs) -> None:
    """Stub for fetch_paper_by_doi that always returns None."""
    return None


def _make_runner(identifier: str = "10.1234/test") -> GetRunner:
    """Create a GetRunner with all non-CrossRef DOI connectors stubbed out."""
    runner = GetRunner(identifier=identifier)
    for attr in ("_openalex", "_semantic_scholar", "_pubmed", "_arxiv"):
        conn = getattr(runner, attr)
        conn.fetch_paper_by_doi = _noop_fetch_doi
        conn.close = lambda: None
    return runner


# ---------------------------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------------------------


class TestIsLandingPageUrl:
    """Tests for GetRunner._is_landing_page_url."""

    def test_http_url_is_landing_page(self):
        """Plain http:// URLs are landing pages."""
        assert GetRunner._is_landing_page_url("http://example.com/paper") is True

    def test_https_url_is_landing_page(self):
        """Plain https:// URLs are landing pages."""
        assert GetRunner._is_landing_page_url("https://arxiv.org/abs/1706.03762") is True

    def test_doi_org_url_is_not_landing_page(self):
        """https://doi.org/... is NOT a landing page — it is a DOI redirect."""
        assert GetRunner._is_landing_page_url("https://doi.org/10.1234/test") is False

    def test_dx_doi_org_url_is_not_landing_page(self):
        """https://dx.doi.org/... is NOT a landing page."""
        assert GetRunner._is_landing_page_url("https://dx.doi.org/10.1234/test") is False

    def test_bare_doi_is_not_landing_page(self):
        """Bare DOI strings are not URLs and therefore not landing pages."""
        assert GetRunner._is_landing_page_url("10.1234/test") is False


# ---------------------------------------------------------------------------
# DOI sanitization
# ---------------------------------------------------------------------------


class TestSanitizeDoi:
    """Tests for GetRunner._sanitize_doi."""

    def test_bare_doi_unchanged(self):
        """A bare DOI passes through unchanged."""
        assert GetRunner._sanitize_doi("10.1234/test") == "10.1234/test"

    def test_https_prefix_stripped(self):
        """https://doi.org/ prefix is stripped."""
        assert GetRunner._sanitize_doi("https://doi.org/10.1234/test") == "10.1234/test"

    def test_http_prefix_stripped(self):
        """http://doi.org/ prefix is stripped."""
        assert GetRunner._sanitize_doi("http://doi.org/10.1234/test") == "10.1234/test"

    def test_dx_prefix_stripped(self):
        """https://dx.doi.org/ prefix is stripped."""
        assert GetRunner._sanitize_doi("https://dx.doi.org/10.1234/test") == "10.1234/test"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is removed."""
        assert GetRunner._sanitize_doi("  10.1234/test  ") == "10.1234/test"

    def test_empty_raises(self):
        """Empty string raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            GetRunner._sanitize_doi("")

    def test_blank_raises(self):
        """Whitespace-only string raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            GetRunner._sanitize_doi("   ")

    def test_prefix_only_raises(self):
        """A bare doi.org URL with no DOI raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            GetRunner._sanitize_doi("https://doi.org/")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestGetRunnerInit:
    """Tests for GetRunner initialisation."""

    def test_default_timeout(self):
        """Default timeout is 10.0 seconds."""
        runner = GetRunner(identifier="10.1234/test")
        assert runner._timeout == 10.0

    def test_custom_timeout(self):
        """Custom timeout is stored."""
        runner = GetRunner(identifier="10.1234/test", timeout=30.0)
        assert runner._timeout == 30.0

    def test_timeout_propagated_to_crossref(self):
        """Custom timeout is forwarded to the CrossRef connector."""
        runner = GetRunner(identifier="10.1234/test", timeout=42.0)
        assert runner._crossref._timeout == 42.0

    def test_timeout_propagated_to_all_doi_connectors(self):
        """Custom timeout is forwarded to every DOI connector."""
        runner = GetRunner(identifier="10.1234/test", timeout=25.0)
        for connector in runner._doi_connectors:
            assert connector._timeout == 25.0

    def test_timeout_propagated_to_scraper(self):
        """Custom timeout is also forwarded to the WebScrapingConnector."""
        runner = GetRunner(identifier="10.1234/test", timeout=15.0)
        assert runner._scraper._timeout == 15.0

    def test_ieee_connector_absent_without_key(self):
        """IEEE connector is None when no API key is provided."""
        runner = GetRunner(identifier="10.1234/test")
        assert runner._ieee is None

    def test_scopus_connector_absent_without_key(self):
        """Scopus connector is None when no API key is provided."""
        runner = GetRunner(identifier="10.1234/test")
        assert runner._scopus is None


# ---------------------------------------------------------------------------
# run() — bare DOI path
# ---------------------------------------------------------------------------


class TestGetRunnerDoiPath:
    """Tests for run() when identifier is a bare DOI or doi.org URL."""

    def test_bare_doi_returns_paper(self):
        """run() returns a Paper when CrossRef finds the DOI."""
        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=fake_paper,
            ),
        ):
            runner = _make_runner("10.1234/test")
            result = runner.run()

        assert result is fake_paper

    def test_doi_org_url_stripped_and_found(self):
        """run() strips the doi.org prefix and resolves the paper correctly."""
        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=fake_paper,
            ),
        ):
            runner = _make_runner("https://doi.org/10.1234/test")
            result = runner.run()

        assert result is fake_paper

    def test_bare_doi_returns_none_when_not_found(self):
        """run() returns None when no connector finds the DOI."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner("10.9999/nonexistent")
            result = runner.run()

        assert result is None

    def test_bare_doi_merges_extra_connector_results(self):
        """DOI connectors beyond CrossRef have their data merged in."""
        base_paper = _fake_paper(keywords=None)
        extra_paper = Paper(
            title="Fake Paper Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            doi="10.1234/test",
            keywords={"ML", "AI"},
            databases={"semantic_scholar"},
        )
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=base_paper,
            ),
        ):
            runner = _make_runner()
            runner._semantic_scholar.fetch_paper_by_doi = lambda doi: extra_paper  # type: ignore[method-assign]
            result = runner.run()

        assert result is base_paper
        assert result.keywords is not None
        assert "ML" in result.keywords

    def test_crossref_url_has_priority(self):
        """CrossRef URL is preserved even when a later connector has a longer URL."""
        base_paper = _fake_paper(url="https://doi.org/10.1234/test")
        extra_paper = Paper(
            title="Fake Paper Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            doi="10.1234/test",
            url="https://www.some-publisher.com/articles/very-long-url/10.1234/test",
            databases={"openalex"},
        )
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=base_paper,
            ),
        ):
            runner = _make_runner()
            runner._openalex.fetch_paper_by_doi = lambda doi: extra_paper  # type: ignore[method-assign]
            result = runner.run()

        assert result is not None
        assert result.url == "https://doi.org/10.1234/test"

    def test_fallback_when_crossref_returns_none(self):
        """When CrossRef finds nothing, another connector can still provide a result."""
        fallback_paper = _fake_paper(databases={"openalex"})
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner()
            runner._openalex.fetch_paper_by_doi = lambda doi: fallback_paper  # type: ignore[method-assign]
            result = runner.run()

        assert result is fallback_paper

    def test_verbose_mode_does_not_raise(self):
        """run() with verbose=True completes without raising."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner()
            result = runner.run(verbose=True)

        assert result is None


# ---------------------------------------------------------------------------
# run() — landing-page URL path
# ---------------------------------------------------------------------------


class TestGetRunnerUrlPath:
    """Tests for run() when identifier is a landing-page URL."""

    def test_url_scraping_result_returned_without_doi(self):
        """When scraping finds a paper but no DOI, Stage 2 is skipped."""
        scraped_paper = _fake_paper(doi=None)
        with patch(
            "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
            return_value=scraped_paper,
        ):
            runner = GetRunner(identifier="https://example.com/paper")
            result = runner.run()

        assert result is scraped_paper

    def test_url_scraping_returns_none_when_page_has_no_metadata(self):
        """run() returns None when the page yields no paper."""
        with patch(
            "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
            return_value=None,
        ):
            runner = GetRunner(identifier="https://example.com/no-meta")
            result = runner.run()

        assert result is None

    def test_url_scraping_enriched_by_doi_connectors(self):
        """When scraping finds a DOI, DOI connectors enrich the scraped paper."""
        scraped_paper = _fake_paper(
            doi="10.1234/test", title="Scraped Title", databases={"web_scraping"}
        )
        crossref_paper = _fake_paper(keywords={"NLP"}, databases={"crossref"})

        mock_scraper = MagicMock(return_value=scraped_paper)
        with (
            patch(
                "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
                mock_scraper,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=crossref_paper,
            ),
        ):
            runner = _make_runner("https://example.com/paper")
            result = runner.run()

        # The scraper paper is the base; CrossRef data is merged in.
        assert result is scraped_paper
        assert result.keywords is not None
        assert "NLP" in result.keywords

    def test_url_lookup_connector_delegates_without_html_scraping(self):
        """When a URL-lookup connector matches, HTML scraping is bypassed."""
        api_paper = _fake_paper(doi=None, databases={"arxiv"})
        with patch(
            "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
            return_value=api_paper,
        ):
            runner = GetRunner(identifier="https://arxiv.org/abs/1706.03762")
            result = runner.run()

        # The paper from the API connector is returned (no DOI → Stage 2 skipped).
        assert result is api_paper

    def test_scraping_failure_falls_through_to_none(self):
        """When scraping raises, the runner returns None instead of propagating."""
        with patch(
            "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
            side_effect=Exception("network error"),
        ):
            runner = GetRunner(identifier="https://example.com/paper")
            result = runner.run()

        assert result is None

    def test_crossref_url_priority_after_url_scraping(self):
        """CrossRef URL takes priority even when the scraped paper had a different URL."""
        scraped_paper = _fake_paper(doi="10.1234/test", url="https://example.com/paper")
        crossref_paper = _fake_paper(url="https://doi.org/10.1234/test", databases={"crossref"})

        with (
            patch(
                "findpapers.connectors.web_scraping.WebScrapingConnector.fetch_paper_from_url",
                return_value=scraped_paper,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=crossref_paper,
            ),
        ):
            runner = _make_runner("https://example.com/paper")
            result = runner.run()

        assert result is scraped_paper
        assert result.url == "https://doi.org/10.1234/test"

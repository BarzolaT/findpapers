"""Unit tests for DOILookupRunner."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source
from findpapers.exceptions import InvalidParameterError
from findpapers.runners.doi_lookup_runner import DOILookupRunner


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


def _fake_paper(title: str = "Fake Paper Title") -> Paper:
    """Return a paper as it would be built from the fake CrossRef work."""
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=[Author(name="Alice Smith")],
        source=Source(title="Fake Journal"),
        publication_date=datetime.date(2023, 6, 15),
        doi="10.1234/test",
        citations=42,
    )


def _patch_all_extra_connectors_as_none():
    """Return a context-manager stack that makes all non-CrossRef connectors return None.

    This avoids live network calls in unit tests that only care about
    CrossRef behaviour.
    """
    return patch.multiple(
        "findpapers.runners.doi_lookup_runner",
        **{},  # no-op placeholder; real patches added below
    )


def _noop_fetch(*_args, **_kwargs) -> None:
    """Stub for fetch_paper_by_doi that always returns None."""
    return None


# ---------------------------------------------------------------------------
# DOI sanitization
# ---------------------------------------------------------------------------


class TestDOISanitization:
    """Tests for DOI input sanitization."""

    def test_bare_doi_unchanged(self):
        """A bare DOI is kept as-is."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._doi == "10.1234/test"

    def test_https_prefix_stripped(self):
        """Common https://doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="https://doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"

    def test_http_prefix_stripped(self):
        """http://doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="http://doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"

    def test_dx_prefix_stripped(self):
        """https://dx.doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="https://dx.doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is removed."""
        runner = DOILookupRunner(doi="  10.1234/test  ")
        assert runner._doi == "10.1234/test"

    def test_empty_doi_raises(self):
        """An empty DOI raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            DOILookupRunner(doi="")

    def test_blank_doi_raises(self):
        """A whitespace-only DOI raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            DOILookupRunner(doi="   ")

    def test_prefix_only_raises(self):
        """A DOI that is only the URL prefix raises InvalidParameterError."""
        with pytest.raises(InvalidParameterError, match="must not be empty"):
            DOILookupRunner(doi="https://doi.org/")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestDOILookupRunnerInit:
    """Tests for DOILookupRunner initialisation."""

    def test_default_timeout(self):
        """Default timeout is 10.0 seconds."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._timeout == 10.0

    def test_custom_timeout(self):
        """Custom timeout is stored."""
        runner = DOILookupRunner(doi="10.1234/test", timeout=30.0)
        assert runner._timeout == 30.0

    def test_timeout_propagated_to_crossref_connector(self):
        """Custom timeout is forwarded to the CrossRefConnector."""
        runner = DOILookupRunner(doi="10.1234/test", timeout=42.0)
        assert runner._crossref._timeout == 42.0

    def test_timeout_propagated_to_all_connectors(self):
        """Custom timeout is forwarded to every connector."""
        runner = DOILookupRunner(doi="10.1234/test", timeout=25.0)
        for connector in runner._all_connectors:
            assert connector._timeout == 25.0

    def test_default_timeout_propagated_to_crossref(self):
        """Default timeout (10.0) is forwarded to CrossRefConnector."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._crossref._timeout == 10.0


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def _make_runner_with_mocked_connectors(doi: str = "10.1234/test") -> DOILookupRunner:
    """Create a runner whose extra connectors are pre-stubbed to return None.

    Only the CrossRef connector is left un-mocked; callers patch it separately.
    IEEE and Scopus are None when no key is provided, so they are skipped.
    """
    runner = DOILookupRunner(doi=doi)
    for attr in ("_openalex", "_semantic_scholar", "_pubmed", "_arxiv", "_ieee", "_scopus"):
        conn = getattr(runner, attr)
        if conn is None:
            continue
        conn.fetch_paper_by_doi = _noop_fetch
        conn.close = lambda: None
    return runner


class TestDOILookupRunnerRun:
    """Tests for the run() method."""

    def test_run_returns_paper_on_success(self):
        """run() returns a Paper when CrossRef returns valid data."""
        fake_work = _fake_crossref_work()
        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=fake_work,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=fake_paper,
            ),
        ):
            runner = _make_runner_with_mocked_connectors()
            result = runner.run()

        assert result is fake_paper

    def test_run_returns_none_when_no_database_finds_doi(self):
        """run() returns None when every database returns nothing."""
        runner = _make_runner_with_mocked_connectors(doi="10.9999/nonexistent")
        runner._crossref.fetch_work = lambda doi: None  # type: ignore[method-assign]
        runner._crossref.close = lambda: None  # type: ignore[method-assign]
        result = runner.run()
        assert result is None

    def test_run_returns_none_when_crossref_not_found_and_others_return_none(self):
        """run() returns None when CrossRef returns 404 and no fallback finds it."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner_with_mocked_connectors()
            result = runner.run()

        assert result is None

    def test_run_returns_none_when_paper_cannot_be_built(self):
        """run() returns None when CrossRef work exists but build_paper returns None."""
        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value={"title": []},
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=None,
            ),
        ):
            runner = _make_runner_with_mocked_connectors()
            result = runner.run()

        assert result is None

    def test_run_passes_doi_to_fetch_work(self):
        """run() forwards the DOI to the connector's fetch_work method."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ) as mock_fetch:
            runner = _make_runner_with_mocked_connectors()
            runner.run()

        mock_fetch.assert_called_once_with("10.1234/test")

    def test_run_verbose_mode(self):
        """run() with verbose=True does not raise."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner_with_mocked_connectors()
            result = runner.run(verbose=True)

        assert result is None

    def test_run_merges_extra_connector_data_into_base(self):
        """Extra connectors' results are merged into the CrossRef base paper."""
        base_paper = _fake_paper()  # no keywords
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
            runner = _make_runner_with_mocked_connectors()
            # Override one extra connector to return extra_paper.
            runner._semantic_scholar.fetch_paper_by_doi = lambda doi: extra_paper  # type: ignore[method-assign]
            result = runner.run()

        # The keywords from semantic scholar should have been merged in.
        assert result is base_paper
        assert result.keywords is not None
        assert "ML" in result.keywords

    def test_run_uses_fallback_when_crossref_returns_none(self):
        """When CrossRef returns None another connector can still provide a result."""
        fallback_paper = _fake_paper()

        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner_with_mocked_connectors()
            runner._openalex.fetch_paper_by_doi = lambda doi: fallback_paper  # type: ignore[method-assign]
            result = runner.run()

        assert result is fallback_paper

    def test_run_can_be_called_multiple_times(self):
        """Calling run() twice updates the result."""
        with patch(
            "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            return_value=None,
        ):
            runner = _make_runner_with_mocked_connectors()
            first = runner.run()

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
            second = runner.run()

        assert first is None
        assert second is fake_paper

    def test_crossref_url_has_priority_over_other_sources(self):
        """CrossRef URL is preserved as the final URL even when another source has a longer one."""
        base_paper = _fake_paper()
        base_paper.url = "https://doi.org/10.1234/test"  # short CrossRef URL

        extra_paper = Paper(
            title="Fake Paper Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            doi="10.1234/test",
            url="https://www.some-publisher.com/journal/articles/very-long-url-from-openalex/10.1234/test",
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
            runner = _make_runner_with_mocked_connectors()
            runner._openalex.fetch_paper_by_doi = lambda doi: extra_paper  # type: ignore[method-assign]
            result = runner.run()

        # Despite the longer URL from OpenAlex, the CrossRef URL must be kept.
        assert result is not None
        assert result.url == "https://doi.org/10.1234/test"

    def test_crossref_url_priority_not_applied_when_crossref_url_is_none(self):
        """When CrossRef returns no URL, another source's URL is kept."""
        base_paper = _fake_paper()
        base_paper.url = None  # CrossRef provided no URL

        extra_paper = Paper(
            title="Fake Paper Title",
            abstract="",
            authors=[],
            source=None,
            publication_date=None,
            doi="10.1234/test",
            url="https://www.openalex.org/works/W123",
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
            runner = _make_runner_with_mocked_connectors()
            runner._openalex.fetch_paper_by_doi = lambda doi: extra_paper  # type: ignore[method-assign]
            result = runner.run()

        # CrossRef URL was None, so the fallback URL from OpenAlex must be used.
        assert result is not None
        assert result.url == "https://www.openalex.org/works/W123"

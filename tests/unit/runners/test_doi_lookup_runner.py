"""Unit tests for DOILookupRunner."""

from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source
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


def _fake_paper() -> Paper:
    """Return a paper as it would be built from the fake CrossRef work."""
    return Paper(
        title="Fake Paper Title",
        abstract="An abstract.",
        authors=[Author(name="Alice Smith")],
        source=Source(title="Fake Journal"),
        publication_date=datetime.date(2023, 6, 15),
        doi="10.1234/test",
        citations=42,
    )


# ---------------------------------------------------------------------------
# DOI sanitization
# ---------------------------------------------------------------------------


class TestDOISanitization:
    """Tests for DOI input sanitization."""

    def test_bare_doi_unchanged(self):
        """A bare DOI is kept as-is."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._doi == "10.1234/test"  # noqa: SLF001

    def test_https_prefix_stripped(self):
        """Common https://doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="https://doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"  # noqa: SLF001

    def test_http_prefix_stripped(self):
        """http://doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="http://doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"  # noqa: SLF001

    def test_dx_prefix_stripped(self):
        """https://dx.doi.org/ prefix is stripped."""
        runner = DOILookupRunner(doi="https://dx.doi.org/10.1234/test")
        assert runner._doi == "10.1234/test"  # noqa: SLF001

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is removed."""
        runner = DOILookupRunner(doi="  10.1234/test  ")
        assert runner._doi == "10.1234/test"  # noqa: SLF001

    def test_empty_doi_raises(self):
        """An empty DOI raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            DOILookupRunner(doi="")

    def test_blank_doi_raises(self):
        """A whitespace-only DOI raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            DOILookupRunner(doi="   ")

    def test_prefix_only_raises(self):
        """A DOI that is only the URL prefix raises ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            DOILookupRunner(doi="https://doi.org/")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestDOILookupRunnerInit:
    """Tests for DOILookupRunner initialisation."""

    def test_default_timeout(self):
        """Default timeout is 10.0 seconds."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._timeout == 10.0  # noqa: SLF001

    def test_custom_timeout(self):
        """Custom timeout is stored."""
        runner = DOILookupRunner(doi="10.1234/test", timeout=30.0)
        assert runner._timeout == 30.0  # noqa: SLF001

    def test_not_executed_by_default(self):
        """Runner is not marked as executed on creation."""
        runner = DOILookupRunner(doi="10.1234/test")
        assert runner._executed is False  # noqa: SLF001


# ---------------------------------------------------------------------------
# get_result / get_runtime before run()
# ---------------------------------------------------------------------------


class TestDOILookupRunnerBeforeRun:
    """Tests for accessing results before run() is called."""

    def test_get_result_before_run_raises(self):
        """get_result() before run() raises RuntimeError."""
        runner = DOILookupRunner(doi="10.1234/test")
        with pytest.raises(RuntimeError, match="has not been executed"):
            runner.get_result()

    def test_get_runtime_before_run_raises(self):
        """get_runtime() before run() raises RuntimeError."""
        runner = DOILookupRunner(doi="10.1234/test")
        with pytest.raises(RuntimeError, match="has not been executed"):
            runner.get_runtime()


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


class TestDOILookupRunnerRun:
    """Tests for the run() method."""

    def test_run_returns_paper_on_success(self):
        """run() returns a Paper when CrossRef returns valid data."""
        fake_work = _fake_crossref_work()
        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
                return_value=fake_work,
            ),
            patch(
                "findpapers.runners.doi_lookup_runner.build_paper_from_crossref",
                return_value=fake_paper,
            ),
        ):
            runner = DOILookupRunner(doi="10.1234/test")
            result = runner.run()

        assert result is fake_paper

    def test_run_returns_none_when_doi_not_found(self):
        """run() returns None when CrossRef returns 404."""
        with patch(
            "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
            return_value=None,
        ):
            runner = DOILookupRunner(doi="10.9999/nonexistent")
            result = runner.run()

        assert result is None

    def test_run_returns_none_when_paper_cannot_be_built(self):
        """run() returns None when build_paper_from_crossref returns None."""
        with (
            patch(
                "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
                return_value={"title": []},
            ),
            patch(
                "findpapers.runners.doi_lookup_runner.build_paper_from_crossref",
                return_value=None,
            ),
        ):
            runner = DOILookupRunner(doi="10.1234/bad")
            result = runner.run()

        assert result is None

    def test_run_passes_timeout_to_fetch(self):
        """run() forwards the timeout parameter to fetch_crossref_work."""
        with patch(
            "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
            return_value=None,
        ) as mock_fetch:
            runner = DOILookupRunner(doi="10.1234/test", timeout=25.0)
            runner.run()

        mock_fetch.assert_called_once_with("10.1234/test", timeout=25.0)

    def test_get_result_after_run(self):
        """get_result() returns the same object as run()."""
        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.runners.doi_lookup_runner.build_paper_from_crossref",
                return_value=fake_paper,
            ),
        ):
            runner = DOILookupRunner(doi="10.1234/test")
            run_result = runner.run()
            get_result = runner.get_result()

        assert run_result is get_result

    def test_get_runtime_after_run(self):
        """get_runtime() returns a non-negative float after run()."""
        with patch(
            "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
            return_value=None,
        ):
            runner = DOILookupRunner(doi="10.1234/test")
            runner.run()

        assert runner.get_runtime() >= 0.0

    def test_run_verbose_mode(self):
        """run() with verbose=True does not raise."""
        with patch(
            "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
            return_value=None,
        ):
            runner = DOILookupRunner(doi="10.1234/test")
            result = runner.run(verbose=True)

        assert result is None

    def test_run_can_be_called_multiple_times(self):
        """Calling run() twice updates the result."""
        with patch(
            "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
            return_value=None,
        ):
            runner = DOILookupRunner(doi="10.1234/test")
            first = runner.run()

        fake_paper = _fake_paper()
        with (
            patch(
                "findpapers.runners.doi_lookup_runner.fetch_crossref_work",
                return_value=_fake_crossref_work(),
            ),
            patch(
                "findpapers.runners.doi_lookup_runner.build_paper_from_crossref",
                return_value=fake_paper,
            ),
        ):
            second = runner.run()

        assert first is None
        assert second is fake_paper
        assert runner.get_result() is fake_paper

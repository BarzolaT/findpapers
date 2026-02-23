"""Unit tests for EnrichmentRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.source import Source
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.enrichment_runner import EnrichmentRunner

# Minimal metadata dict that makes fetch_metadata look successful (HTML with a title).
_FAKE_METADATA: dict = {"citation_title": "Test Paper"}


def _make_paper(title: str = "Test Paper", urls: set[str] | None = None) -> Paper:
    """Create a minimal Paper for testing."""
    url = (
        None
        if urls is not None and len(urls) == 0
        else (next(iter(urls)) if urls else "http://example.com/paper")
    )
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=[Author(name="Author One")],
        source=Source(title="Test Journal"),
        publication_date=date(2023, 1, 1),
        url=url,
    )


class TestEnrichmentRunnerInit:
    """Tests for EnrichmentRunner initialisation."""

    def test_init_stores_papers(self):
        """Constructor stores a copy of the paper list."""
        papers = [_make_paper()]
        runner = EnrichmentRunner(papers=papers)
        assert runner._results is not papers  # noqa: SLF001
        assert len(runner._results) == 1  # noqa: SLF001

    def test_get_metrics_before_run_raises(self):
        """get_metrics() before run() raises SearchRunnerNotExecutedError."""
        runner = EnrichmentRunner(papers=[_make_paper()])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.get_metrics()


class TestEnrichmentRunnerRun:
    """Tests for the run() method."""

    def test_run_with_empty_papers(self):
        """run() on empty list completes without errors."""
        runner = EnrichmentRunner(papers=[])
        runner.run()
        metrics = runner.get_metrics()
        assert metrics["total_papers"] == 0
        assert metrics["enriched_papers"] == 0

    def test_metrics_populated_after_run(self):
        """Metrics contain all expected keys after run()."""
        runner = EnrichmentRunner(papers=[_make_paper()])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            runner.run()
        metrics = runner.get_metrics()
        assert "total_papers" in metrics
        assert "enriched_papers" in metrics
        assert "doi_enriched_papers" in metrics
        assert "fetch_error_papers" in metrics
        assert "no_metadata_papers" in metrics
        assert "no_change_papers" in metrics
        assert "no_urls_papers" in metrics
        assert "runtime_in_seconds" in metrics

    def test_enriched_count_incremented_on_success(self):
        """enriched_papers increments only when new data is actually merged.

        The base paper is missing a DOI; the mock enriched paper supplies one,
        so the merge changes the snapshot and the counter must increment.
        """
        base = _make_paper()
        base.doi = None  # ensure the field is absent before enrichment
        enriched_paper = _make_paper(title="Enriched")
        enriched_paper.doi = "10.1234/test"
        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=enriched_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[base])
            runner.run()
        assert runner.get_metrics()["enriched_papers"] == 1

    def test_enriched_count_not_incremented_when_no_change(self):
        """enriched_papers stays 0 when the merge adds nothing new.

        The base paper already has all the data the scraped paper can offer,
        so the snapshot is unchanged and the counter must not increment.
        """
        same_paper = _make_paper()
        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=same_paper,  # identical data — no improvement
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[_make_paper()])
            runner.run()
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_skips_papers_without_urls(self):
        """Papers without URLs (and no DOI) return 'no_urls' without fetching."""
        paper = _make_paper(urls=set())  # url=None
        paper.doi = None  # ensure no DOI fallback URL either
        runner = EnrichmentRunner(papers=[paper])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata") as mock_fetch,
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work") as mock_crossref,
        ):
            runner.run()
        mock_fetch.assert_not_called()
        mock_crossref.assert_not_called()
        metrics = runner.get_metrics()
        assert metrics["enriched_papers"] == 0
        assert metrics["no_urls_papers"] == 1

    def test_run_twice_resets(self):
        """run() can be called multiple times; metrics are fresh each time."""
        runner = EnrichmentRunner(papers=[_make_paper()])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            runner.run()
            runner.run()
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_parallel_run(self):
        """Parallel run completes and returns metrics."""
        papers = [_make_paper(f"Paper {i}") for i in range(5)]
        runner = EnrichmentRunner(papers=papers, num_workers=3)
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            runner.run()
        assert runner.get_metrics()["total_papers"] == 5

    def test_fetch_error_counted_when_url_raises(self):
        """fetch_error_papers counts papers whose URL fetch raised an HTTP/network error."""
        paper = _make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch(
            "findpapers.runners.enrichment_runner.fetch_metadata",
            side_effect=RuntimeError("network error"),
        ):
            runner.run()
        assert runner.get_metrics()["fetch_error_papers"] == 1
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_no_metadata_counted_when_fetch_returns_none(self):
        """no_metadata_papers counts papers whose URL returned non-HTML content."""
        paper = _make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None):
            runner.run()
        assert runner.get_metrics()["no_metadata_papers"] == 1
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_no_change_counted_when_merge_changes_nothing(self):
        """no_change_papers counts papers where HTML was fetched but added no new data."""
        same_paper = _make_paper()
        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=same_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[_make_paper()])
            runner.run()
        assert runner.get_metrics()["no_change_papers"] == 1
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_doi_url_added_as_candidate(self):
        """When the paper has a DOI, https://doi.org/{doi} is tried as a candidate URL."""
        paper = _make_paper()
        paper.doi = "10.1234/test"
        fetched_urls: list[str] = []

        def _record_fetch(url: str, timeout: object = None) -> None:  # type: ignore[return]
            fetched_urls.append(url)
            return None  # simulate non-HTML / no-metadata response

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                side_effect=_record_fetch,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()
        assert "https://doi.org/10.1234/test" in fetched_urls


class TestEnrichmentRunnerVerbose:
    """Tests for the verbose=True logging path."""

    def test_verbose_run_does_not_raise(self):
        """run(verbose=True) completes without raising."""
        runner = EnrichmentRunner(papers=[])
        runner.run(verbose=True)
        assert runner.get_metrics()["total_papers"] == 0

    def test_verbose_true_emits_configuration_header(self, caplog):
        """verbose=True logs the EnrichmentRunner configuration header."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=True)
        assert "EnrichmentRunner Configuration" in " ".join(caplog.messages)

    def test_verbose_true_emits_enrichment_summary(self, caplog):
        """verbose=True logs the enrichment summary after execution."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Enrichment Summary" in messages
        assert "Runtime" in messages

    def test_verbose_true_tracks_fetch_errors(self):
        """Fetch errors are counted in fetch_error_papers when URLs raise."""
        paper = _make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch(
            "findpapers.runners.enrichment_runner.fetch_metadata",
            side_effect=RuntimeError("network error"),
        ):
            runner.run(verbose=True)
        assert runner.get_metrics()["fetch_error_papers"] == 1

    def test_verbose_false_emits_no_configuration_log(self, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with (
            patch("findpapers.runners.enrichment_runner.fetch_metadata", return_value=None),
            patch("findpapers.runners.enrichment_runner.fetch_crossref_work", return_value=None),
        ):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=False)
        assert "EnrichmentRunner Configuration" not in " ".join(caplog.messages)

    def test_verbose_true_suppresses_third_party_loggers(self):
        """verbose=True sets noisy third-party loggers to WARNING to avoid credential leaks."""
        import logging

        runner = EnrichmentRunner(papers=[])
        runner.run(verbose=True)
        for lib in ("urllib3", "requests", "httpx", "charset_normalizer"):
            assert logging.getLogger(lib).level == logging.WARNING


class TestEnrichmentRunnerCrossRef:
    """Tests for DOI-based enrichment via the CrossRef API."""

    def test_crossref_enriches_paper_with_doi(self):
        """Papers with a DOI attempt CrossRef API enrichment."""
        paper = _make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None  # missing data that CrossRef will fill

        crossref_paper = _make_paper(title="CrossRef Paper")
        crossref_paper.citations = 42

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value={"title": ["CrossRef Paper"]},
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_crossref",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        metrics = runner.get_metrics()
        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert paper.citations == 42

    def test_crossref_not_called_without_doi(self):
        """Papers without DOI skip CrossRef entirely."""
        paper = _make_paper()
        paper.doi = None

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
            ) as mock_crossref,
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        mock_crossref.assert_not_called()

    def test_crossref_error_falls_back_to_url_scraping(self):
        """CrossRef error does not prevent URL-based enrichment."""
        paper = _make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None

        enriched_paper = _make_paper(title="Scraped")
        enriched_paper.citations = 10

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                side_effect=RuntimeError("CrossRef timeout"),
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=enriched_paper,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        metrics = runner.get_metrics()
        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 0
        assert paper.citations == 10

    def test_crossref_and_scraping_both_contribute(self):
        """Both CrossRef and URL scraping can contribute data to the same paper."""
        paper = _make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None
        paper.pdf_url = None

        # CrossRef provides citations but not pdf_url
        crossref_paper = _make_paper(title="CrossRef")
        crossref_paper.citations = 100
        crossref_paper.pdf_url = None

        # URL scraping provides pdf_url
        scraped_paper = _make_paper(title="Scraped")
        scraped_paper.pdf_url = "https://example.com/paper.pdf"
        scraped_paper.citations = None

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value={"title": ["CrossRef"]},
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_crossref",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=scraped_paper,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        metrics = runner.get_metrics()
        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert paper.citations == 100
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_doi_only_paper_no_urls_enriches_via_crossref(self):
        """Paper with DOI but no URL can still be enriched via CrossRef."""
        paper = _make_paper(urls=set())
        paper.doi = "10.1234/test"
        paper.citations = None

        crossref_paper = _make_paper(title="CrossRef Only")
        crossref_paper.citations = 55

        with (
            patch(
                "findpapers.runners.enrichment_runner.fetch_crossref_work",
                return_value={"title": ["CrossRef Only"]},
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_crossref",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.fetch_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        metrics = runner.get_metrics()
        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert metrics["no_urls_papers"] == 0

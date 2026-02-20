"""Unit tests for EnrichmentRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from findpapers.core.paper import Paper
from findpapers.core.source import Source
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.enrichment_runner import EnrichmentRunner


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
        authors=["Author One"],
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
        """Metrics contain expected keys after run()."""
        runner = EnrichmentRunner(papers=[_make_paper()])
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
            runner.run()
        metrics = runner.get_metrics()
        assert "total_papers" in metrics
        assert "enriched_papers" in metrics
        assert "runtime_in_seconds" in metrics

    def test_enriched_count_incremented_on_success(self):
        """enriched_papers count increments when enrich succeeds."""
        enriched_paper = _make_paper(title="Enriched")
        with patch(
            "findpapers.runners.enrichment_runner.enrich_from_sources",
            return_value=enriched_paper,
        ):
            runner = EnrichmentRunner(papers=[_make_paper()])
            runner.run()
        assert runner.get_metrics()["enriched_papers"] == 1

    def test_skips_papers_without_urls(self):
        """Papers without URLs are skipped (not enriched)."""
        paper = _make_paper(urls=set())  # url=None
        runner = EnrichmentRunner(papers=[paper])
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources") as mock_enrich:
            runner.run()
        mock_enrich.assert_not_called()
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_run_twice_resets(self):
        """run() can be called multiple times; metrics are fresh each time."""
        runner = EnrichmentRunner(papers=[_make_paper()])
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
            runner.run()
            runner.run()
        assert runner.get_metrics()["enriched_papers"] == 0

    def test_parallel_run(self):
        """Parallel run completes and returns metrics."""
        papers = [_make_paper(f"Paper {i}") for i in range(5)]
        runner = EnrichmentRunner(papers=papers, num_workers=3)
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
            runner.run()
        assert runner.get_metrics()["total_papers"] == 5


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
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=True)
        assert "EnrichmentRunner Configuration" in " ".join(caplog.messages)

    def test_verbose_true_emits_enrichment_summary(self, caplog):
        """verbose=True logs the enrichment summary after execution."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Enrichment Summary" in messages
        assert "Runtime" in messages

    def test_verbose_true_logs_enrichment_error(self, caplog):
        """verbose=True logs a WARNING when a paper fails to enrich."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with patch(
            "findpapers.runners.enrichment_runner.enrich_from_sources",
            side_effect=RuntimeError("network error"),
        ):
            with caplog.at_level(logging.WARNING, logger="findpapers.runners.enrichment_runner"):
                runner.run(verbose=True)
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1

    def test_verbose_false_emits_no_configuration_log(self, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = EnrichmentRunner(papers=[_make_paper()])
        with patch("findpapers.runners.enrichment_runner.enrich_from_sources", return_value=None):
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


class TestEnrichmentRunnerPredatoryReclassification:
    """Tests for predatory flag reclassification after enrichment."""

    def test_predatory_flag_set_when_publication_found_after_enrichment(self):
        """Paper without publication gets predatory flag after enrichment fills in a predatory pub."""
        paper = Paper(
            title="No Pub Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )
        assert paper.source is None

        predatory_pub = Source(title="Predatory Journal XYZ")
        enriched_paper = Paper(
            title="No Pub Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=predatory_pub,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )

        with (
            patch(
                "findpapers.runners.enrichment_runner.enrich_from_sources",
                return_value=enriched_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.is_predatory_source",
                return_value=True,
            ) as mock_is_predatory,
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        mock_is_predatory.assert_called_once()
        assert paper.source is not None
        assert paper.source.is_potentially_predatory is True

    def test_predatory_flag_cleared_when_publication_is_safe(self):
        """Paper originally flagged as predatory is cleared if enrichment resolves a safe pub."""
        safe_pub = Source(title="Legitimate Journal")
        original_pub = Source(title="Unknown", is_potentially_predatory=True)
        paper = Paper(
            title="Flagged Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=original_pub,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )

        enriched_paper = Paper(
            title="Flagged Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=safe_pub,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )

        with (
            patch(
                "findpapers.runners.enrichment_runner.enrich_from_sources",
                return_value=enriched_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.is_predatory_source",
                return_value=False,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        assert paper.source is not None
        assert paper.source.is_potentially_predatory is False

    def test_predatory_flag_skipped_when_no_publication_after_enrichment(self):
        """Predatory flag is not changed when enrichment does not provide a publication."""
        paper = Paper(
            title="No Pub Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )

        enriched_paper = Paper(
            title="No Pub Paper",
            abstract="Abstract.",
            authors=["Author"],
            source=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/paper",
        )

        with (
            patch(
                "findpapers.runners.enrichment_runner.enrich_from_sources",
                return_value=enriched_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.is_predatory_source",
            ) as mock_is_predatory,
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        mock_is_predatory.assert_not_called()
        assert paper.source is None

"""Unit tests for SearchRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.search_result import Database
from findpapers.core.source import Source
from findpapers.exceptions import UnsupportedQueryError
from findpapers.runners.search_runner import SearchRunner, _are_years_compatible


class TestSearchRunnerInit:
    """Tests for SearchRunner initialisation."""

    def test_invalid_query_raises(self):
        """Malformed query raises QueryValidationError at construction time."""
        from findpapers.exceptions import QueryValidationError

        with pytest.raises(QueryValidationError):
            SearchRunner(query="((bad query")

    def test_unknown_database_raises_on_run(self):
        """Providing an unknown database name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown database"):
            SearchRunner(query="[machine learning]", databases=["nonexistent_db"])

    def test_valid_init(self):
        """Valid query and known databases initialise without error."""
        runner = SearchRunner(
            query="[machine learning]",
            databases=["arxiv", "pubmed"],
        )
        assert len(runner._searchers) == 2  # noqa: SLF001

    def test_all_databases_when_none(self):
        """4 databases are selected when databases=None and no API keys given.

        IEEE and Scopus require API keys; without them they are skipped.
        """
        runner = SearchRunner(query="[ml]")
        assert len(runner._searchers) == 4  # noqa: SLF001

    def test_all_databases_when_api_keys_provided(self):
        """All 6 databases are selected when databases=None and API keys given."""
        runner = SearchRunner(
            query="[ml]",
            ieee_api_key="ieee_key",
            scopus_api_key="scopus_key",
        )
        assert len(runner._searchers) == 6  # noqa: SLF001

    def test_ieee_skipped_without_api_key(self):
        """IEEE is excluded from the searcher list when no API key is given."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "ieee"])
        names = [s.name for s in runner._searchers]  # noqa: SLF001
        assert "ieee" not in names
        assert "arxiv" in names

    def test_ieee_included_with_api_key(self):
        """IEEE is included when its API key is provided."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "ieee"], ieee_api_key="key")
        names = [s.name for s in runner._searchers]  # noqa: SLF001
        assert "ieee" in names

    def test_scopus_skipped_without_api_key(self):
        """Scopus is excluded from the searcher list when no API key is given."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "scopus"])
        names = [s.name for s in runner._searchers]  # noqa: SLF001
        assert "scopus" not in names
        assert "arxiv" in names

    def test_scopus_included_with_api_key(self):
        """Scopus is included when its API key is provided."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "scopus"], scopus_api_key="key")
        names = [s.name for s in runner._searchers]  # noqa: SLF001
        assert "scopus" in names

    def test_skipped_databases_recorded_when_no_key(self):
        """_skipped_databases lists names of databases dropped due to missing keys."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "ieee", "scopus"])
        assert "ieee" in runner._skipped_databases  # noqa: SLF001
        assert "scopus" in runner._skipped_databases  # noqa: SLF001
        assert "arxiv" not in runner._skipped_databases  # noqa: SLF001

    def test_skipped_databases_empty_when_keys_provided(self):
        """_skipped_databases is empty when all required keys are present."""
        runner = SearchRunner(
            query="[ml]",
            databases=["arxiv", "ieee", "scopus"],
            ieee_api_key="key",
            scopus_api_key="key",
        )
        assert runner._skipped_databases == []  # noqa: SLF001


class TestSearchRunnerPipeline:
    """Tests for the full pipeline via run()."""

    def _make_runner_with_mock_papers(self, papers: list[Paper]) -> SearchRunner:
        """Create a SearchRunner whose searchers return the provided papers."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = papers
        runner._searchers = [mock_searcher]  # noqa: SLF001
        return runner

    def test_run_returns_search_object(self, make_paper):
        """run() returns a SearchResult instance."""
        from findpapers.core.search_result import SearchResult

        runner = self._make_runner_with_mock_papers([make_paper()])
        result = runner.run()
        assert isinstance(result, SearchResult)

    def test_run_closes_searcher_sessions(self, make_paper):
        """run() closes all searcher sessions after execution."""
        runner = self._make_runner_with_mock_papers([make_paper()])
        mock_searcher: MagicMock = runner._searchers[0]  # type: ignore[assignment]  # noqa: SLF001
        runner.run()
        mock_searcher.close.assert_called_once()

    def test_run_closes_sessions_on_searcher_error(self):
        """Searcher sessions are closed even when a searcher raises during fetch."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = RuntimeError("boom")
        runner._searchers = [mock_searcher]  # noqa: SLF001

        # execute_tasks catches the error internally, so run() completes.
        runner.run()
        mock_searcher.close.assert_called_once()

    def test_get_results_after_run(self, make_paper):
        """run() result contains the collected papers."""
        paper = make_paper()
        runner = self._make_runner_with_mock_papers([paper])
        result = runner.run()
        assert len(result.papers) == 1
        assert result.papers[0].title == paper.title

    def test_metrics_populated_after_run(self, make_paper):
        """SearchResult contains runtime after run()."""
        runner = self._make_runner_with_mock_papers([make_paper()])
        result = runner.run()
        assert result.runtime_seconds is not None
        assert result.runtime_seconds >= 0

    def test_metrics_include_zero_for_skipped_databases(self, make_paper):
        """Skipped databases (no API key) do not break the run."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "ieee"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [make_paper()]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_merges_same_doi(self, make_paper):
        """Two papers with the same DOI are merged into one."""
        p1 = make_paper(title="Paper A", doi="10.1234/test")
        p2 = make_paper(title="Paper B", doi="10.1234/test")
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_keeps_different_dois(self, make_paper):
        """Papers with different DOIs *and* different titles are kept separately."""
        p1 = make_paper(title="Paper A", doi="10.1234/aaa")
        p2 = make_paper(title="Paper B", doi="10.1234/bbb")
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 2

    def test_deduplication_second_pass_merges_same_title_different_doi(self, make_paper):
        """Pass 2 merges papers with the same title even when DOIs differ.

        This covers the common cross-database case where the same work is
        indexed with an arXiv DOI in one database and the publisher DOI in
        another (e.g. ``10.48550/arxiv.1706.03762`` vs ``10.5555/3295222.3295349``
        for "Attention is All You Need").
        """
        p1 = make_paper(title="Attention is All You Need", doi="10.48550/arxiv.1706.03762")
        p2 = make_paper(title="Attention is All You Need", doi="10.5555/3295222.3295349")
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_second_pass_merges_same_title_one_without_year(self):
        """Pass 2 merges same-title papers when one lacks a publication date.

        This is the canonical cross-database case: a preprint indexed by
        arXiv may carry a publication date while the same work indexed by
        OpenAlex (or another database) has no publication_date in its record.
        The two copies must be merged rather than kept as separate duplicates.
        """
        p1 = Paper(
            title="Attention is All You Need",
            abstract="abstract with year",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="arXiv"),
            publication_date=date(2017, 6, 12),
            url="http://arxiv.org/abs/1706.03762",
            doi="10.48550/arxiv.1706.03762",
        )
        p2 = Paper(
            title="Attention is All You Need",
            abstract="abstract without year",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="OpenAlex Source"),
            publication_date=None,  # intentionally missing
            url="http://openalex.org/W2963403868",
            doi="10.5555/3295222.3295349",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_second_pass_keeps_same_title_different_year(self):
        """Papers with the same title but different publication years are kept separate."""
        p1 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=date(2022, 1, 1),
            url="http://example.com/2022",
            doi="10.1234/ai-2022",
        )
        p2 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=date(2023, 1, 1),
            url="http://example.com/2023",
            doi="10.1234/ai-2023",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 2

    def test_deduplication_second_pass_merges_preprints_across_year_boundary(self):
        """Same preprint on two servers across Dec/Jan boundary is merged into one.

        This is the canonical Zenodo+SSRN cross-year scenario: a preprint
        deposited to Zenodo on 2025-12-25 and mirrored to SSRN on 2026-01-01
        receives different DOIs from each platform.  After pass 1 both entries
        survive (different DOIs).  Pass 2 must detect that (a) both DOIs are
        preprint DOIs and (b) the years differ by exactly 1, and therefore
        merge them rather than reporting a duplicate title.
        """
        p1 = Paper(
            title="Attention is All You Need... Unless You Are a CISO",
            abstract="abstract from zenodo",
            authors=[Author(name="Author A")],
            source=Source(title="Zenodo"),
            publication_date=date(2025, 12, 25),
            url="https://zenodo.org/records/18056028",
            doi="10.5281/zenodo.18056028",
        )
        p2 = Paper(
            title="Attention is All You Need... Unless You Are a CISO",
            abstract="abstract from ssrn",
            authors=[Author(name="Author A")],
            source=Source(title="SSRN"),
            publication_date=date(2026, 1, 1),
            url="https://ssrn.com/abstract=5967774",
            doi="10.2139/ssrn.5967774",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_second_pass_merges_preprint_with_published_version(self):
        """Preprint DOI + publisher DOI with adjacent years are merged into one.

        The common "preprint-to-published" case: a Zenodo deposit from 2026
        and a book chapter from 2025 share the same title.  Only the Zenodo
        record is a preprint, but that is sufficient for the year-adjacent rule
        to fire — the old ``both_preprints`` requirement was too strict and
        left such pairs as false duplicates.
        """
        p1 = Paper(
            title="Attention is All You Need",
            abstract="preprint version",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="Zenodo"),
            publication_date=date(2026, 1, 17),
            url="https://zenodo.org/records/18289747",
            doi="10.5281/zenodo.18289747",
        )
        p2 = Paper(
            title="Attention Is All You Need",
            abstract="book chapter version",
            authors=[Author(name="Vaswani et al.")],
            source=Source(title="Deep Learning Book"),
            publication_date=date(2025, 10, 31),
            url="https://doi.org/10.1201/9781003561460-19",
            doi="10.1201/9781003561460-19",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 1

    def test_deduplication_second_pass_keeps_non_preprint_adjacent_years(self):
        """Two non-preprint papers with same title and adjacent years are kept separate.

        If neither DOI is a preprint, the year-adjacent rule must NOT fire —
        annual reports and series papers with consecutive-year DOIs are
        intentionally distinct entries.
        """
        p1 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=date(2022, 1, 1),
            url="http://example.com/2022",
            doi="10.1234/ai-2022",
        )
        p2 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=[Author(name="A")],
            source=Source(title="Journal"),
            publication_date=date(2023, 1, 1),
            url="http://example.com/2023",
            doi="10.1234/ai-2023",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 2

    def test_deduplication_second_pass_keeps_preprints_with_large_year_gap(self):
        """Preprints with the same title but years >1 apart are kept separate."""
        p1 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2022",
            authors=[Author(name="Author A")],
            source=Source(title="Zenodo"),
            publication_date=date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.5281/zenodo.1",
        )
        p2 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2024",
            authors=[Author(name="Author B")],
            source=Source(title="arXiv"),
            publication_date=date(2024, 6, 1),
            url="https://arxiv.org/abs/2406.00001",
            doi="10.48550/arxiv.2406.00001",
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        result = runner.run()
        assert len(result.papers) == 2

    def test_run_can_be_called_twice(self, make_paper):
        """Calling run() twice resets previous results."""
        papers1 = [make_paper(title="First")]
        runner = self._make_runner_with_mock_papers(papers1)
        result = runner.run()
        assert len(result.papers) == 1

        # Replace mock to return different papers on second call.
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [make_paper(title="A"), make_paper(title="B")]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert len(result.papers) == 2

    def test_searcher_error_is_handled_gracefully(self):
        """If a searcher raises an exception, run() still completes."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = RuntimeError("network error")
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert len(result.papers) == 0

    def test_unsupported_query_error_emits_warning(self, caplog):
        """UnsupportedQueryError from a searcher emits a warning regardless of verbose."""
        import logging

        from findpapers.exceptions import UnsupportedQueryError

        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = UnsupportedQueryError(
            "Search on 'arXiv' aborted: incompatible query."
        )
        runner._searchers = [mock_searcher]  # noqa: SLF001

        with caplog.at_level(logging.WARNING, logger="findpapers.runners.search_runner"):
            runner.run(verbose=False)  # verbose=False: warning must still appear

        assert any("arXiv" in m or "Skipping" in m for m in caplog.messages), (
            f"Expected warning not found in: {caplog.messages}"
        )

    def test_regular_error_warning_requires_verbose(self, caplog):
        """A generic searcher error only emits a warning when verbose=True."""
        import logging

        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = RuntimeError("network timeout")
        runner._searchers = [mock_searcher]  # noqa: SLF001

        with caplog.at_level(logging.WARNING, logger="findpapers.runners.search_runner"):
            runner.run(verbose=False)

        warning_messages = [
            m for m in caplog.messages if "network timeout" in m or "Error fetching" in m
        ]
        assert warning_messages == [], "Generic error should not warn when verbose=False"


class TestSearchRunnerVerbose:
    """Tests for the verbose=True logging path."""

    def _make_runner_with_mock_papers(self, papers: list[Paper]) -> SearchRunner:
        """Create a SearchRunner whose searchers return the provided papers."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = papers
        runner._searchers = [mock_searcher]  # noqa: SLF001
        return runner

    def test_verbose_run_does_not_raise(self, make_paper, caplog):
        """run(verbose=True) completes without raising."""
        import logging

        runner = self._make_runner_with_mock_papers([make_paper()])
        with caplog.at_level(logging.INFO):
            result = runner.run(verbose=True)
        # No exception raised; runner should be executed.
        assert len(result.papers) >= 0

    def test_verbose_true_emits_configuration_header(self, make_paper, caplog):
        """verbose=True logs the configuration header."""
        import logging

        runner = self._make_runner_with_mock_papers([make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "SearchRunner Configuration" in messages

    def test_verbose_true_emits_results_summary(self, make_paper, caplog):
        """verbose=True logs the results summary."""
        import logging

        runner = self._make_runner_with_mock_papers([make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Results" in messages
        assert "Runtime" in messages

    def test_verbose_false_emits_no_configuration_log(self, make_paper, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = self._make_runner_with_mock_papers([make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=False)
        assert "SearchRunner Configuration" not in " ".join(caplog.messages)

    def test_show_progress_false_disables_progress_bars(self, make_paper):
        """show_progress=False suppresses tqdm progress bars."""
        from unittest.mock import patch

        runner = self._make_runner_with_mock_papers([make_paper()])
        with patch("findpapers.runners.search_runner.make_progress_bar") as mock_pbar:
            mock_ctx = MagicMock()
            mock_pbar.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_pbar.return_value.__exit__ = MagicMock(return_value=False)
            runner.run(show_progress=False)
            # Verify that make_progress_bar was called with disable=True
            for call in mock_pbar.call_args_list:
                assert call.kwargs.get("disable") is True or (
                    len(call.args) > 3 and call.args[3] is True
                )

    def test_show_progress_true_enables_progress_bars(self, make_paper):
        """show_progress=True (default) enables tqdm progress bars."""
        from unittest.mock import patch

        runner = self._make_runner_with_mock_papers([make_paper()])
        with patch("findpapers.runners.search_runner.make_progress_bar") as mock_pbar:
            mock_ctx = MagicMock()
            mock_pbar.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_pbar.return_value.__exit__ = MagicMock(return_value=False)
            runner.run(show_progress=True)
            # Verify that make_progress_bar was called with disable=False
            for call in mock_pbar.call_args_list:
                assert call.kwargs.get("disable") is False


class TestSearchRunnerParallel:
    """Tests for parallel execution."""

    def test_num_workers_runs_all_searchers(self, make_paper):
        """Parallel mode (num_workers > 1) still returns results from all searchers."""
        mock_s1 = MagicMock()
        mock_s1.name = "arXiv"
        mock_s1.search.return_value = [make_paper(title="A")]
        mock_s2 = MagicMock()
        mock_s2.name = "PubMed"
        mock_s2.search.return_value = [make_paper(title="B")]

        runner = SearchRunner(query="[ml]", databases=["arxiv", "pubmed"], num_workers=2)
        runner._searchers = [mock_s1, mock_s2]  # noqa: SLF001
        result = runner.run()
        assert len(result.papers) == 2

    def test_num_workers_capped_to_number_of_searchers(self, make_paper):
        """num_workers is capped to the number of configured searchers."""
        mock_s1 = MagicMock()
        mock_s1.name = "arXiv"
        mock_s1.search.return_value = [make_paper(title="A")]
        mock_s2 = MagicMock()
        mock_s2.name = "PubMed"
        mock_s2.search.return_value = [make_paper(title="B")]

        # num_workers=10 but only 2 searchers — effective workers must be capped to 2.
        runner = SearchRunner(query="[ml]", databases=["arxiv", "pubmed"], num_workers=10)
        runner._searchers = [mock_s1, mock_s2]  # noqa: SLF001

        captured: list[int | None] = []
        original_execute = __import__(
            "findpapers.utils.parallel", fromlist=["execute_tasks"]
        ).execute_tasks

        def _capture_execute(tasks, fn, *, num_workers, **kwargs):
            captured.append(num_workers)
            return original_execute(tasks, fn, num_workers=num_workers, **kwargs)

        import findpapers.runners.search_runner as sr_mod

        original = sr_mod.execute_tasks
        sr_mod.execute_tasks = _capture_execute  # type: ignore[assignment]
        try:
            result = runner.run()
        finally:
            sr_mod.execute_tasks = original

        assert captured == [2], f"Expected num_workers=2, got {captured}"
        assert len(result.papers) == 2


class TestSearchRunnerFailedDatabases:
    """Tests for tracking databases that fail during search."""

    def test_no_failures_gives_empty_list(self, make_paper):
        """When all searchers succeed, failed_databases is empty."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [make_paper()]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert result.failed_databases == []

    def test_runtime_error_records_failure(self):
        """A database that raises RuntimeError is recorded in failed_databases."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = RuntimeError("network down")
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert Database.ARXIV in result.failed_databases

    def test_unsupported_query_not_recorded(self):
        """Databases skipped via UnsupportedQueryError are NOT in failed_databases."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = UnsupportedQueryError("not supported")
        runner._searchers = [mock_searcher]  # noqa: SLF001
        result = runner.run()
        assert result.failed_databases == []

    def test_mixed_success_and_failure(self, make_paper):
        """Only the failing database is recorded; the successful one is not."""
        runner = SearchRunner(query="[ml]", databases=["arxiv", "ieee"])
        ok_searcher = MagicMock()
        ok_searcher.name = Database.ARXIV
        ok_searcher.search.return_value = [make_paper()]
        bad_searcher = MagicMock()
        bad_searcher.name = Database.IEEE
        bad_searcher.search.side_effect = RuntimeError("timeout")
        runner._searchers = [ok_searcher, bad_searcher]  # noqa: SLF001
        result = runner.run()
        assert result.failed_databases == [Database.IEEE]
        assert len(result.papers) == 1


# ---------------------------------------------------------------------------
# _are_years_compatible
# ---------------------------------------------------------------------------


class TestAreYearsCompatible:
    """Tests for the extracted _are_years_compatible helper."""

    def test_same_year_compatible(self) -> None:
        """Identical years are always compatible."""
        assert _are_years_compatible(2025, 2025, None, None) is True

    def test_none_year_a_compatible(self) -> None:
        """Unknown year_a makes pair compatible."""
        assert _are_years_compatible(None, 2025, None, None) is True

    def test_none_year_b_compatible(self) -> None:
        """Unknown year_b makes pair compatible."""
        assert _are_years_compatible(2025, None, None, None) is True

    def test_both_none_compatible(self) -> None:
        """Both years unknown is compatible."""
        assert _are_years_compatible(None, None, None, None) is True

    def test_different_years_no_doi_incompatible(self) -> None:
        """Different years without DOIs are not compatible."""
        assert _are_years_compatible(2024, 2025, None, None) is False

    def test_different_years_non_preprint_doi_incompatible(self) -> None:
        """Different years with non-preprint DOIs are not compatible."""
        assert _are_years_compatible(2024, 2025, "10.1038/x", "10.1016/y") is False

    def test_adjacent_year_preprint_doi_compatible(self) -> None:
        """Adjacent years with a preprint DOI (arXiv) are compatible."""
        assert _are_years_compatible(2025, 2026, "10.48550/arXiv.123", "10.1038/x") is True

    def test_two_year_gap_preprint_incompatible(self) -> None:
        """Years separated by >1 are not compatible even with preprint DOI."""
        assert _are_years_compatible(2024, 2026, "10.48550/arXiv.123", "10.1038/x") is False

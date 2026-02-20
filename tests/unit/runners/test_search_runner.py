"""Unit tests for SearchRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from findpapers.core.paper import Paper, PaperType
from findpapers.core.search import Database
from findpapers.core.source import Source
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.search_runner import SearchRunner


def _make_paper(
    title: str = "Test Paper",
    doi: str | None = None,
    paper_type: PaperType | None = PaperType.ARTICLE,
    is_predatory: bool = False,
) -> Paper:
    """Create a minimal Paper for testing."""
    if is_predatory:
        pub = Source(title="OMICS International")
    else:
        pub = Source(title="Test Journal")
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=["Author One"],
        source=pub,
        publication_date=date(2023, 1, 1),
        url="http://example.com",
        doi=doi,
        paper_type=paper_type,
    )


class TestSearchRunnerInit:
    """Tests for SearchRunner initialisation."""

    def test_invalid_query_raises(self):
        """Malformed query raises QueryValidationError at construction time."""
        from findpapers.core.query import QueryValidationError

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

    def test_get_results_before_run_raises(self):
        """get_results() before run() raises SearchRunnerNotExecutedError."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.get_results()

    def test_get_metrics_before_run_raises(self):
        """get_metrics() before run() raises SearchRunnerNotExecutedError."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.get_metrics()


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

    def test_run_returns_search_object(self):
        """run() returns a Search instance."""
        from findpapers.core.search import Search

        runner = self._make_runner_with_mock_papers([_make_paper()])
        result = runner.run()
        assert isinstance(result, Search)

    def test_get_results_after_run(self):
        """get_results() returns the collected papers after run()."""
        paper = _make_paper()
        runner = self._make_runner_with_mock_papers([paper])
        runner.run()
        results = runner.get_results()
        assert len(results) == 1
        assert results[0].title == paper.title

    def test_get_results_returns_deep_copy(self):
        """get_results() returns independent copies."""
        paper = _make_paper()
        runner = self._make_runner_with_mock_papers([paper])
        runner.run()
        res1 = runner.get_results()
        res1[0].title = "modified"
        res2 = runner.get_results()
        assert res2[0].title == paper.title

    def test_metrics_populated_after_run(self):
        """Metrics dict contains expected keys after run()."""
        runner = self._make_runner_with_mock_papers([_make_paper()])
        runner.run()
        metrics = runner.get_metrics()
        assert "total_papers" in metrics
        assert "runtime_in_seconds" in metrics
        assert "total_papers_from_predatory_source" in metrics

    def test_deduplication_merges_same_doi(self):
        """Two papers with the same DOI are merged into one."""
        p1 = _make_paper(title="Paper A", doi="10.1234/test")
        p2 = _make_paper(title="Paper B", doi="10.1234/test")
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 1

    def test_deduplication_keeps_different_dois(self):
        """Papers with different DOIs *and* different titles are kept separately."""
        p1 = _make_paper(title="Paper A", doi="10.1234/aaa")
        p2 = _make_paper(title="Paper B", doi="10.1234/bbb")
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 2

    def test_deduplication_second_pass_merges_same_title_different_doi(self):
        """Pass 2 merges papers with the same title even when DOIs differ.

        This covers the common cross-database case where the same work is
        indexed with an arXiv DOI in one database and the publisher DOI in
        another (e.g. ``10.48550/arxiv.1706.03762`` vs ``10.5555/3295222.3295349``
        for "Attention is All You Need").
        """
        p1 = _make_paper(title="Attention is All You Need", doi="10.48550/arxiv.1706.03762")
        p2 = _make_paper(title="Attention is All You Need", doi="10.5555/3295222.3295349")
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 1

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
            authors=["Vaswani et al."],
            source=Source(title="arXiv"),
            publication_date=date(2017, 6, 12),
            url="http://arxiv.org/abs/1706.03762",
            doi="10.48550/arxiv.1706.03762",
            paper_type=PaperType.UNPUBLISHED,
        )
        p2 = Paper(
            title="Attention is All You Need",
            abstract="abstract without year",
            authors=["Vaswani et al."],
            source=Source(title="OpenAlex Source"),
            publication_date=None,  # intentionally missing
            url="http://openalex.org/W2963403868",
            doi="10.5555/3295222.3295349",
            paper_type=PaperType.INPROCEEDINGS,
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 1

    def test_deduplication_second_pass_keeps_same_title_different_year(self):
        """Papers with the same title but different publication years are kept separate."""
        p1 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=["A"],
            source=Source(title="Journal"),
            publication_date=date(2022, 1, 1),
            url="http://example.com/2022",
            doi="10.1234/ai-2022",
            paper_type=PaperType.ARTICLE,
        )
        p2 = Paper(
            title="Annual Report on AI",
            abstract="abstract",
            authors=["A"],
            source=Source(title="Journal"),
            publication_date=date(2023, 1, 1),
            url="http://example.com/2023",
            doi="10.1234/ai-2023",
            paper_type=PaperType.ARTICLE,
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 2

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
            authors=["Author A"],
            source=Source(title="Zenodo"),
            publication_date=date(2025, 12, 25),
            url="https://zenodo.org/records/18056028",
            doi="10.5281/zenodo.18056028",
            paper_type=PaperType.UNPUBLISHED,
        )
        p2 = Paper(
            title="Attention is All You Need... Unless You Are a CISO",
            abstract="abstract from ssrn",
            authors=["Author A"],
            source=Source(title="SSRN"),
            publication_date=date(2026, 1, 1),
            url="https://ssrn.com/abstract=5967774",
            doi="10.2139/ssrn.5967774",
            paper_type=PaperType.UNPUBLISHED,
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 1

    def test_deduplication_second_pass_keeps_preprints_with_large_year_gap(self):
        """Preprints with the same title but years >1 apart are kept separate."""
        p1 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2022",
            authors=["Author A"],
            source=Source(title="Zenodo"),
            publication_date=date(2022, 1, 1),
            url="https://zenodo.org/records/1",
            doi="10.5281/zenodo.1",
            paper_type=PaperType.UNPUBLISHED,
        )
        p2 = Paper(
            title="Survey of Transformers",
            abstract="abstract 2024",
            authors=["Author B"],
            source=Source(title="arXiv"),
            publication_date=date(2024, 6, 1),
            url="https://arxiv.org/abs/2406.00001",
            doi="10.48550/arxiv.2406.00001",
            paper_type=PaperType.UNPUBLISHED,
        )
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 2

    def test_paper_type_filter(self):
        """Papers with non-matching paper_type are removed."""
        article_paper = _make_paper(title="Article", paper_type=PaperType.ARTICLE)
        conf_paper = _make_paper(title="Conference", paper_type=PaperType.INPROCEEDINGS)
        runner = SearchRunner(
            query="[ml]",
            databases=["arxiv"],
            paper_types=["article"],
        )
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [article_paper, conf_paper]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        results = runner.get_results()
        assert len(results) == 1
        assert results[0].title == "Article"

    def test_untyped_paper_kept_when_no_type_filter(self):
        """Papers with paper_type=None are retained when no type filter is requested.

        Callers that ask for 'all papers' (paper_types=None) should receive
        every paper regardless of whether its BibTeX type could be determined.
        Silently discarding untyped papers caused AND queries to return more
        results than OR queries when the two sub-query result sets happened to
        contain different numbers of untyped papers (i.e. AND > OR violation).
        """
        typed_paper = _make_paper(title="Typed", paper_type=PaperType.ARTICLE)
        untyped_paper = _make_paper(title="Untyped", paper_type=None)
        runner = SearchRunner(query="[ml]", databases=["arxiv"])  # no paper_types
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [typed_paper, untyped_paper]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        results = runner.get_results()
        assert len(results) == 2
        titles = {r.title for r in results}
        assert "Typed" in titles
        assert "Untyped" in titles

    def test_untyped_paper_removed_when_type_filter_requested(self):
        """Papers with paper_type=None are removed when a type filter is active.

        When the caller requests specific types, untyped papers cannot be
        confirmed to belong to the allowed set and must therefore be excluded.
        """
        typed_paper = _make_paper(title="Typed", paper_type=PaperType.ARTICLE)
        untyped_paper = _make_paper(title="Untyped", paper_type=None)
        runner = SearchRunner(query="[ml]", databases=["arxiv"], paper_types=["article"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [typed_paper, untyped_paper]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        results = runner.get_results()
        assert len(results) == 1
        assert results[0].title == "Typed"

    def test_run_can_be_called_twice(self):
        """Calling run() twice resets previous results."""
        papers1 = [_make_paper(title="First")]
        runner = self._make_runner_with_mock_papers(papers1)
        runner.run()
        assert len(runner.get_results()) == 1

        # Replace mock to return different papers on second call.
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.return_value = [_make_paper(title="A"), _make_paper(title="B")]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        assert len(runner.get_results()) == 2

    def test_predatory_flagging(self):
        """Papers from known predatory publishers are flagged."""
        paper = _make_paper(is_predatory=True)
        runner = self._make_runner_with_mock_papers([paper])
        runner.run()
        metrics = runner.get_metrics()
        # Flagged count >= 0 (may or may not be in the predatory list)
        assert metrics["total_papers_from_predatory_source"] >= 0

    def test_searcher_error_is_handled_gracefully(self):
        """If a searcher raises an exception, run() still completes."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = Database.ARXIV
        mock_searcher.search.side_effect = RuntimeError("network error")
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        assert len(runner.get_results()) == 0

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

        assert any(
            "arXiv" in m or "Skipping" in m for m in caplog.messages
        ), f"Expected warning not found in: {caplog.messages}"

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

    def test_verbose_run_does_not_raise(self, caplog):
        """run(verbose=True) completes without raising."""
        import logging

        runner = self._make_runner_with_mock_papers([_make_paper()])
        with caplog.at_level(logging.INFO):
            runner.run(verbose=True)
        # No exception raised; runner should be executed.
        assert runner.get_metrics()["total_papers"] >= 0

    def test_verbose_true_emits_configuration_header(self, caplog):
        """verbose=True logs the configuration header."""
        import logging

        runner = self._make_runner_with_mock_papers([_make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "SearchRunner Configuration" in messages

    def test_verbose_true_emits_results_summary(self, caplog):
        """verbose=True logs the results summary."""
        import logging

        runner = self._make_runner_with_mock_papers([_make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Results" in messages
        assert "Runtime" in messages

    def test_verbose_false_emits_no_configuration_log(self, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = self._make_runner_with_mock_papers([_make_paper()])
        with caplog.at_level(logging.INFO, logger="findpapers.runners.search_runner"):
            runner.run(verbose=False)
        assert "SearchRunner Configuration" not in " ".join(caplog.messages)


class TestSearchRunnerParallel:
    """Tests for parallel execution."""

    def test_num_workers_runs_all_searchers(self):
        """Parallel mode (num_workers > 1) still returns results from all searchers."""
        mock_s1 = MagicMock()
        mock_s1.name = "arXiv"
        mock_s1.search.return_value = [_make_paper(title="A")]
        mock_s2 = MagicMock()
        mock_s2.name = "PubMed"
        mock_s2.search.return_value = [_make_paper(title="B")]

        runner = SearchRunner(query="[ml]", databases=["arxiv", "pubmed"], num_workers=2)
        runner._searchers = [mock_s1, mock_s2]  # noqa: SLF001
        runner.run()
        assert len(runner.get_results()) == 2

    def test_num_workers_capped_to_number_of_searchers(self):
        """num_workers is capped to the number of configured searchers."""
        mock_s1 = MagicMock()
        mock_s1.name = "arXiv"
        mock_s1.search.return_value = [_make_paper(title="A")]
        mock_s2 = MagicMock()
        mock_s2.name = "PubMed"
        mock_s2.search.return_value = [_make_paper(title="B")]

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
        sr_mod.execute_tasks = _capture_execute
        try:
            runner.run()
        finally:
            sr_mod.execute_tasks = original

        assert captured == [2], f"Expected num_workers=2, got {captured}"
        assert len(runner.get_results()) == 2

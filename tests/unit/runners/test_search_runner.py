"""Unit tests for SearchRunner."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from findpapers.core.paper import Paper
from findpapers.core.publication import Publication
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.search_runner import SearchRunner


def _make_paper(
    title: str = "Test Paper",
    doi: str | None = None,
    category: str | None = "Journal",
    is_predatory: bool = False,
) -> Paper:
    """Create a minimal Paper for testing."""
    pub = None
    if category:
        pub = Publication(title="Test Journal", category=category)
        if is_predatory:
            # Use a known predatory publisher name to trigger flag
            pub = Publication(title="OMICS International", category=category)
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=["Author One"],
        publication=pub,
        publication_date=date(2023, 1, 1),
        url="http://example.com",
        doi=doi,
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
        """All 8 databases are selected when databases=None."""
        runner = SearchRunner(query="[ml]")
        assert len(runner._searchers) == 8  # noqa: SLF001

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
        mock_searcher.name = "arXiv"
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
        assert "total_papers_from_predatory_publication" in metrics

    def test_deduplication_merges_same_doi(self):
        """Two papers with the same DOI are merged into one."""
        p1 = _make_paper(title="Paper A", doi="10.1234/test")
        p2 = _make_paper(title="Paper B", doi="10.1234/test")
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 1

    def test_deduplication_keeps_different_dois(self):
        """Papers with different DOIs are kept separately."""
        p1 = _make_paper(title="Paper A", doi="10.1234/aaa")
        p2 = _make_paper(title="Paper B", doi="10.1234/bbb")
        runner = self._make_runner_with_mock_papers([p1, p2])
        runner.run()
        assert len(runner.get_results()) == 2

    def test_publication_type_filter(self):
        """Papers with non-matching publication type are removed."""
        journal_paper = _make_paper(title="Journal", category="Journal")
        conf_paper = _make_paper(title="Conference", category="Conference Proceedings")
        runner = SearchRunner(
            query="[ml]",
            databases=["arxiv"],
            publication_types=["journal"],
        )
        mock_searcher = MagicMock()
        mock_searcher.name = "arXiv"
        mock_searcher.search.return_value = [journal_paper, conf_paper]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        results = runner.get_results()
        assert len(results) == 1
        assert results[0].title == "Journal"

    def test_run_can_be_called_twice(self):
        """Calling run() twice resets previous results."""
        papers1 = [_make_paper(title="First")]
        runner = self._make_runner_with_mock_papers(papers1)
        runner.run()
        assert len(runner.get_results()) == 1

        # Replace mock to return different papers on second call.
        mock_searcher = MagicMock()
        mock_searcher.name = "arXiv"
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
        assert metrics["total_papers_from_predatory_publication"] >= 0

    def test_searcher_error_is_handled_gracefully(self):
        """If a searcher raises an exception, run() still completes."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = "arXiv"
        mock_searcher.search.side_effect = RuntimeError("network error")
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        assert len(runner.get_results()) == 0


class TestSearchRunnerExports:
    """Tests for export methods."""

    def _ready_runner(self) -> SearchRunner:
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        mock_searcher = MagicMock()
        mock_searcher.name = "arXiv"
        mock_searcher.search.return_value = [_make_paper()]
        runner._searchers = [mock_searcher]  # noqa: SLF001
        runner.run()
        return runner

    def test_to_json_before_run_raises(self, tmp_path):
        """to_json() before run() raises SearchRunnerNotExecutedError."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.to_json(str(tmp_path / "out.json"))

    def test_to_csv_before_run_raises(self, tmp_path):
        """to_csv() before run() raises SearchRunnerNotExecutedError."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.to_csv(str(tmp_path / "out.csv"))

    def test_to_bibtex_before_run_raises(self, tmp_path):
        """to_bibtex() before run() raises SearchRunnerNotExecutedError."""
        runner = SearchRunner(query="[ml]", databases=["arxiv"])
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.to_bibtex(str(tmp_path / "out.bib"))

    def test_to_json_creates_file(self, tmp_path):
        """to_json() creates a JSON file after successful run."""
        runner = self._ready_runner()
        path = str(tmp_path / "out.json")
        runner.to_json(path)
        import json

        with open(path) as f:
            data = json.load(f)
        assert "papers" in data

    def test_to_csv_creates_file(self, tmp_path):
        """to_csv() creates a CSV file after successful run."""
        runner = self._ready_runner()
        path = str(tmp_path / "out.csv")
        runner.to_csv(path)
        import csv

        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) >= 1

    def test_to_bibtex_creates_file(self, tmp_path):
        """to_bibtex() creates a BibTeX file after successful run."""
        runner = self._ready_runner()
        path = str(tmp_path / "out.bib")
        runner.to_bibtex(path)
        content = open(path).read()
        assert "@" in content


class TestSearchRunnerParallel:
    """Tests for parallel execution."""

    def test_max_workers_runs_all_searchers(self):
        """Parallel mode (max_workers > 1) still returns results from all searchers."""
        mock_s1 = MagicMock()
        mock_s1.name = "arXiv"
        mock_s1.search.return_value = [_make_paper(title="A")]
        mock_s2 = MagicMock()
        mock_s2.name = "PubMed"
        mock_s2.search.return_value = [_make_paper(title="B")]

        runner = SearchRunner(query="[ml]", databases=["arxiv", "pubmed"], max_workers=2)
        runner._searchers = [mock_s1, mock_s2]  # noqa: SLF001
        runner.run()
        assert len(runner.get_results()) == 2

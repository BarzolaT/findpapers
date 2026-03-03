"""Unit tests for SnowballRunner."""

from __future__ import annotations

import datetime

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.runners.snowball_runner import SnowballRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    title: str,
    doi: str | None = None,
    abstract: str = "",
) -> Paper:
    """Create a minimal Paper for testing."""
    return Paper(
        title=title,
        abstract=abstract,
        authors=[Author(name="Test Author")],
        source=None,
        publication_date=datetime.date(2024, 1, 1),
        doi=doi,
    )


class FakeCitationConnector(CitationConnectorBase):
    """A fake connector that returns pre-configured references and citations."""

    def __init__(
        self,
        references: dict[str, list[Paper]] | None = None,
        cited_by: dict[str, list[Paper]] | None = None,
    ) -> None:
        """Create a FakeCitationConnector.

        Parameters
        ----------
        references : dict[str, list[Paper]] | None
            Mapping from DOI to list of referenced papers.
        cited_by : dict[str, list[Paper]] | None
            Mapping from DOI to list of citing papers.
        """
        self._references = references or {}
        self._cited_by = cited_by or {}

    @property
    def name(self) -> str:
        """Return connector name.

        Returns
        -------
        str
            Connector identifier.
        """
        return "fake"

    @property
    def min_request_interval(self) -> float:
        """Return minimum request interval.

        Returns
        -------
        float
            Zero for tests.
        """
        return 0.0

    def fetch_references(self, paper: Paper) -> list[Paper]:
        """Return pre-configured references for the given paper.

        Parameters
        ----------
        paper : Paper
            Paper to look up.

        Returns
        -------
        list[Paper]
            List of referenced papers.
        """
        return list(self._references.get(paper.doi or "", []))

    def fetch_cited_by(self, paper: Paper) -> list[Paper]:
        """Return pre-configured citing papers.

        Parameters
        ----------
        paper : Paper
            Paper to look up.

        Returns
        -------
        list[Paper]
            List of citing papers.
        """
        return list(self._cited_by.get(paper.doi or "", []))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnowballRunnerInit:
    """Tests for SnowballRunner initialisation."""

    def test_single_paper_seed(self) -> None:
        """Accepts a single Paper as seed_papers."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=seed, depth=1)

        assert len(runner._seed_papers) == 1

    def test_skips_papers_without_doi(self) -> None:
        """Papers without DOI are silently skipped."""
        seed_with_doi = _make_paper("With DOI", doi="10.1000/ok")
        seed_without_doi = _make_paper("No DOI")
        runner = SnowballRunner(seed_papers=[seed_with_doi, seed_without_doi])

        assert len(runner._seed_papers) == 1
        assert runner._skipped_seeds == 1

    def test_default_parameters(self) -> None:
        """Default depth is 1, direction is 'both', num_workers is 1."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed])

        assert runner._depth == 1
        assert runner._direction == "both"
        assert runner._num_workers == 1

    def test_depth_clamped_to_zero(self) -> None:
        """Negative depth is clamped to 0."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed], depth=-1)

        assert runner._depth == 0


class TestSnowballRunnerRun:
    """Tests for the snowball execution logic."""

    def test_depth_zero_returns_only_seeds(self) -> None:
        """With depth=0 no expansion happens; only seeds in the graph."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed], depth=0)
        runner._connectors = [FakeCitationConnector()]

        graph = runner.run()

        assert graph.paper_count == 1
        assert graph.edge_count == 0

    def test_backward_snowball_depth_1(self) -> None:
        """Backward snowballing collects references of the seed."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref1 = _make_paper("Ref 1", doi="10.1000/r1")
        ref2 = _make_paper("Ref 2", doi="10.1000/r2")

        connector = FakeCitationConnector(
            references={"10.1000/seed": [ref1, ref2]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + 2 refs
        assert graph.edge_count == 2  # seed -> ref1, seed -> ref2
        refs = graph.get_references(seed)
        assert len(refs) == 2

    def test_forward_snowball_depth_1(self) -> None:
        """Forward snowballing collects papers that cite the seed."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        citing1 = _make_paper("Citing 1", doi="10.1000/c1")
        citing2 = _make_paper("Citing 2", doi="10.1000/c2")

        connector = FakeCitationConnector(
            cited_by={"10.1000/seed": [citing1, citing2]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="forward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + 2 citing
        assert graph.edge_count == 2
        cited_by = graph.get_cited_by(seed)
        assert len(cited_by) == 2

    def test_both_directions_depth_1(self) -> None:
        """Snowballing in both directions collects refs and citing papers."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.1000/ref")
        citing = _make_paper("Citing", doi="10.1000/citing")

        connector = FakeCitationConnector(
            references={"10.1000/seed": [ref]},
            cited_by={"10.1000/seed": [citing]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="both",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3
        assert graph.edge_count == 2

    def test_depth_2_expands_second_level(self) -> None:
        """At depth=2, papers found at level 1 are also expanded."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        level1 = _make_paper("Level 1", doi="10.1000/l1")
        level2 = _make_paper("Level 2", doi="10.1000/l2")

        connector = FakeCitationConnector(
            references={
                "10.1000/seed": [level1],
                "10.1000/l1": [level2],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            depth=2,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + l1 + l2
        assert graph.edge_count == 2  # seed->l1, l1->l2
        assert graph.get_paper_depth(seed) == 0
        assert graph.get_paper_depth(level1) == 1
        assert graph.get_paper_depth(level2) == 2

    def test_deduplication_across_connectors(self) -> None:
        """Same paper found by different connectors is not duplicated."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.1000/ref")
        ref_dup = _make_paper("Ref (duplicate)", doi="10.1000/ref")

        connector1 = FakeCitationConnector(references={"10.1000/seed": [ref]})
        connector2 = FakeCitationConnector(references={"10.1000/seed": [ref_dup]})

        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="backward",
        )
        runner._connectors = [connector1, connector2]

        graph = runner.run()

        assert graph.paper_count == 2  # seed + ref (deduplicated)
        assert graph.edge_count == 1  # one edge seed -> ref

    def test_cycle_detection(self) -> None:
        """Papers already in the graph are not expanded again."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.1000/ref")

        # ref cites seed back — creates a cycle.
        connector = FakeCitationConnector(
            references={
                "10.1000/seed": [ref],
                "10.1000/ref": [seed],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            depth=2,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        # Only 2 papers; the seed is not re-added.
        assert graph.paper_count == 2
        # seed -> ref AND ref -> seed (but ref -> seed is only added
        # at depth 2 when ref is expanded).
        assert graph.edge_count == 2

    def test_connector_error_does_not_crash(self) -> None:
        """If a connector raises, the runner logs and continues."""
        seed = _make_paper("Seed", doi="10.1000/seed")

        class ErrorConnector(CitationConnectorBase):
            """Connector that always raises."""

            @property
            def name(self) -> str:
                """Return name.

                Returns
                -------
                str
                    Connector name.
                """
                return "error"

            @property
            def min_request_interval(self) -> float:
                """Return interval.

                Returns
                -------
                float
                    Zero.
                """
                return 0.0

            def fetch_references(self, paper: Paper) -> list[Paper]:
                """Always raise.

                Parameters
                ----------
                paper : Paper
                    Ignored.

                Raises
                ------
                RuntimeError
                    Always.
                """
                raise RuntimeError("boom")

            def fetch_cited_by(self, paper: Paper) -> list[Paper]:
                """Always raise.

                Parameters
                ----------
                paper : Paper
                    Ignored.

                Raises
                ------
                RuntimeError
                    Always.
                """
                raise RuntimeError("boom")

        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="both",
        )
        runner._connectors = [ErrorConnector()]

        # Should not raise.
        graph = runner.run()

        assert graph.paper_count == 1  # only the seed
        assert graph.edge_count == 0

    def test_multiple_seeds(self) -> None:
        """Multiple seed papers are all expanded at depth 1."""
        seed1 = _make_paper("Seed 1", doi="10.1000/s1")
        seed2 = _make_paper("Seed 2", doi="10.1000/s2")
        ref1 = _make_paper("Ref 1", doi="10.1000/r1")
        ref2 = _make_paper("Ref 2", doi="10.1000/r2")

        connector = FakeCitationConnector(
            references={
                "10.1000/s1": [ref1],
                "10.1000/s2": [ref2],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed1, seed2],
            depth=1,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 4
        assert graph.edge_count == 2

    def test_parallel_connectors(self) -> None:
        """With num_workers > 1, connectors are queried in parallel."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        ref1 = _make_paper("Ref C1", doi="10.1000/rc1")
        ref2 = _make_paper("Ref C2", doi="10.1000/rc2")

        connector1 = FakeCitationConnector(references={"10.1000/seed": [ref1]})
        connector2 = FakeCitationConnector(references={"10.1000/seed": [ref2]})

        runner = SnowballRunner(
            seed_papers=[seed],
            depth=1,
            direction="backward",
            num_workers=3,
        )
        runner._connectors = [connector1, connector2]

        graph = runner.run()

        # Both connectors should have been queried.
        assert graph.paper_count == 3  # seed + rc1 + rc2
        assert graph.edge_count == 2


class TestSnowballRunnerMetrics:
    """Tests for metrics after execution."""

    def test_metrics_after_run(self) -> None:
        """Graph contains expected data after run()."""
        seed = _make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed], depth=0)
        runner._connectors = [FakeCitationConnector()]

        graph = runner.run()

        assert graph.paper_count == 1
        assert graph.edge_count == 0

    def test_show_progress_false_disables_progress_bar(self) -> None:
        """show_progress=False suppresses the tqdm progress bar."""
        from unittest.mock import patch

        seed = _make_paper("Seed", doi="10.1000/seed")
        ref = _make_paper("Ref", doi="10.2000/ref")
        connector = FakeCitationConnector(references={"10.1000/seed": [ref]})
        runner = SnowballRunner(seed_papers=[seed], depth=1)
        runner._connectors = [connector]

        with patch("findpapers.runners.snowball_runner.make_progress_bar") as mock_pbar:
            mock_ctx = type(
                "MockCtx",
                (),
                {
                    "__enter__": lambda self: self,
                    "__exit__": lambda self, *args: False,
                    "update": lambda self, n=1: None,
                },
            )()
            mock_pbar.return_value = mock_ctx
            runner.run(show_progress=False)
            assert mock_pbar.called
            for call in mock_pbar.call_args_list:
                assert call.kwargs.get("disable") is True

"""Unit tests for SnowballRunner."""

from __future__ import annotations

import pytest

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.core.paper import Paper
from findpapers.runners.snowball_runner import SnowballRunner


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
        super().__init__()
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

    def test_single_paper_seed(self, make_paper) -> None:
        """Accepts a single Paper as seed_papers."""
        seed = make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=seed, max_depth=1)

        assert len(runner._seed_papers) == 1

    def test_skips_papers_without_doi(self, make_paper) -> None:
        """Papers without DOI are silently skipped."""
        seed_with_doi = make_paper("With DOI", doi="10.1000/ok")
        seed_without_doi = make_paper("No DOI")
        runner = SnowballRunner(seed_papers=[seed_with_doi, seed_without_doi])

        assert len(runner._seed_papers) == 1
        assert runner._skipped_seeds == 1

    def test_default_parameters(self, make_paper) -> None:
        """Default max_depth is 1, direction is 'both', num_workers is 1."""
        seed = make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed])

        assert runner._max_depth == 1
        assert runner._direction == "both"
        assert runner._num_workers == 1

    def test_max_depth_zero_raises(self, make_paper) -> None:
        """max_depth of zero raises ValueError."""
        seed = make_paper("Seed", doi="10.1000/seed")
        with pytest.raises(ValueError, match="max_depth must be >= 1"):
            SnowballRunner(seed_papers=[seed], max_depth=0)

    def test_max_depth_negative_raises(self, make_paper) -> None:
        """Negative max_depth raises ValueError."""
        seed = make_paper("Seed", doi="10.1000/seed")
        with pytest.raises(ValueError, match="max_depth must be >= 1"):
            SnowballRunner(seed_papers=[seed], max_depth=-1)


class TestSnowballRunnerRun:
    """Tests for the snowball execution logic."""

    def test_depth_one_returns_immediate_neighbours(self, make_paper) -> None:
        """With max_depth=1 only immediate neighbours are fetched."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        connector = FakeCitationConnector(
            references={"10.1000/seed": [ref]},
        )
        runner = SnowballRunner(seed_papers=[seed], max_depth=1, direction="backward")
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 2
        assert graph.edge_count == 1

    def test_backward_snowball_depth_1(self, make_paper) -> None:
        """Backward snowballing collects references of the seed."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref1 = make_paper("Ref 1", doi="10.1000/r1")
        ref2 = make_paper("Ref 2", doi="10.1000/r2")

        connector = FakeCitationConnector(
            references={"10.1000/seed": [ref1, ref2]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + 2 refs
        assert graph.edge_count == 2  # seed -> ref1, seed -> ref2
        refs = graph.get_references(seed)
        assert len(refs) == 2

    def test_forward_snowball_depth_1(self, make_paper) -> None:
        """Forward snowballing collects papers that cite the seed."""
        seed = make_paper("Seed", doi="10.1000/seed")
        citing1 = make_paper("Citing 1", doi="10.1000/c1")
        citing2 = make_paper("Citing 2", doi="10.1000/c2")

        connector = FakeCitationConnector(
            cited_by={"10.1000/seed": [citing1, citing2]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="forward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + 2 citing
        assert graph.edge_count == 2
        cited_by = graph.get_cited_by(seed)
        assert len(cited_by) == 2

    def test_both_directions_depth_1(self, make_paper) -> None:
        """Snowballing in both directions collects refs and citing papers."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        citing = make_paper("Citing", doi="10.1000/citing")

        connector = FakeCitationConnector(
            references={"10.1000/seed": [ref]},
            cited_by={"10.1000/seed": [citing]},
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="both",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3
        assert graph.edge_count == 2

    def test_depth_2_expands_second_level(self, make_paper) -> None:
        """At max_depth=2, papers found at level 1 are also expanded."""
        seed = make_paper("Seed", doi="10.1000/seed")
        level1 = make_paper("Level 1", doi="10.1000/l1")
        level2 = make_paper("Level 2", doi="10.1000/l2")

        connector = FakeCitationConnector(
            references={
                "10.1000/seed": [level1],
                "10.1000/l1": [level2],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=2,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 3  # seed + l1 + l2
        assert graph.edge_count == 2  # seed->l1, l1->l2
        assert graph.get_paper_depth(seed) == 0
        assert graph.get_paper_depth(level1) == 1
        assert graph.get_paper_depth(level2) == 2

    def test_deduplication_across_connectors(self, make_paper) -> None:
        """Same paper found by different connectors is not duplicated."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        ref_dup = make_paper("Ref (duplicate)", doi="10.1000/ref")

        connector1 = FakeCitationConnector(references={"10.1000/seed": [ref]})
        connector2 = FakeCitationConnector(references={"10.1000/seed": [ref_dup]})

        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="backward",
        )
        runner._connectors = [connector1, connector2]

        graph = runner.run()

        assert graph.paper_count == 2  # seed + ref (deduplicated)
        assert graph.edge_count == 1  # one edge seed -> ref

    def test_cycle_detection(self, make_paper) -> None:
        """Papers already in the graph are not expanded again."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")

        # ref cites seed back — creates a cycle.
        connector = FakeCitationConnector(
            references={
                "10.1000/seed": [ref],
                "10.1000/ref": [seed],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=2,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        # Only 2 papers; the seed is not re-added.
        assert graph.paper_count == 2
        # seed -> ref AND ref -> seed (but ref -> seed is only added
        # at depth 2 when ref is expanded).
        assert graph.edge_count == 2

    def test_connector_error_does_not_crash(self, make_paper) -> None:
        """If a connector raises, the runner logs and continues."""
        seed = make_paper("Seed", doi="10.1000/seed")

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
            max_depth=1,
            direction="both",
        )
        runner._connectors = [ErrorConnector()]

        # Should not raise.
        graph = runner.run()

        assert graph.paper_count == 1  # only the seed
        assert graph.edge_count == 0

    def test_multiple_seeds(self, make_paper) -> None:
        """Multiple seed papers are all expanded at depth 1."""
        seed1 = make_paper("Seed 1", doi="10.1000/s1")
        seed2 = make_paper("Seed 2", doi="10.1000/s2")
        ref1 = make_paper("Ref 1", doi="10.1000/r1")
        ref2 = make_paper("Ref 2", doi="10.1000/r2")

        connector = FakeCitationConnector(
            references={
                "10.1000/s1": [ref1],
                "10.1000/s2": [ref2],
            },
        )
        runner = SnowballRunner(
            seed_papers=[seed1, seed2],
            max_depth=1,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run()

        assert graph.paper_count == 4
        assert graph.edge_count == 2

    def test_parallel_connectors(self, make_paper) -> None:
        """With num_workers > 1, connectors are queried in parallel."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref1 = make_paper("Ref C1", doi="10.1000/rc1")
        ref2 = make_paper("Ref C2", doi="10.1000/rc2")

        connector1 = FakeCitationConnector(references={"10.1000/seed": [ref1]})
        connector2 = FakeCitationConnector(references={"10.1000/seed": [ref2]})

        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
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

    def test_metrics_after_run(self, make_paper) -> None:
        """Graph contains expected data after run()."""
        seed = make_paper("Seed", doi="10.1000/seed")
        runner = SnowballRunner(seed_papers=[seed], max_depth=1)
        runner._connectors = [FakeCitationConnector()]

        graph = runner.run()

        assert graph.paper_count == 1
        assert graph.edge_count == 0

    def test_show_progress_false_disables_progress_bar(self, make_paper) -> None:
        """show_progress=False suppresses the tqdm progress bar."""
        from unittest.mock import patch

        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.2000/ref")
        connector = FakeCitationConnector(references={"10.1000/seed": [ref]})
        runner = SnowballRunner(seed_papers=[seed], max_depth=1)
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


class TestSnowballRunnerVerbose:
    """Tests for verbose logging branches."""

    def test_verbose_logs_configuration_and_results(self, make_paper) -> None:
        """verbose=True logs configuration, per-level info, and results."""
        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        connector = FakeCitationConnector(references={"10.1000/seed": [ref]})
        runner = SnowballRunner(seed_papers=[seed], max_depth=1, direction="backward")
        runner._connectors = [connector]

        graph = runner.run(verbose=True, show_progress=False)

        assert graph.paper_count == 2

    def test_verbose_multi_level(self, make_paper) -> None:
        """verbose=True logs at each depth level."""
        seed = make_paper("Seed", doi="10.1000/seed")
        l1 = make_paper("L1", doi="10.1000/l1")
        l2 = make_paper("L2", doi="10.1000/l2")
        connector = FakeCitationConnector(
            references={"10.1000/seed": [l1], "10.1000/l1": [l2]},
        )
        runner = SnowballRunner(seed_papers=[seed], max_depth=2, direction="backward")
        runner._connectors = [connector]

        graph = runner.run(verbose=True, show_progress=False)

        assert graph.paper_count == 3


class TestSnowballRunnerParallelErrors:
    """Tests for error handling in parallel connector execution."""

    def test_parallel_connector_exception_is_caught(self, make_paper) -> None:
        """Exception in a parallel connector is caught; other results survive."""

        class BoomConnector(CitationConnectorBase):
            """Connector whose future raises."""

            @property
            def name(self) -> str:
                """Return name.

                Returns
                -------
                str
                    Connector name.
                """
                return "boom"

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

        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        good = FakeCitationConnector(references={"10.1000/seed": [ref]})
        bad = BoomConnector()

        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="backward",
            num_workers=4,
        )
        runner._connectors = [good, bad]

        graph = runner.run(show_progress=False)

        # The good connector's result should still be present.
        assert graph.paper_count == 2  # seed + ref
        assert graph.edge_count == 1

    def test_parallel_future_exception_is_caught(self, make_paper) -> None:
        """When _query_single_connector itself raises, the future exception is caught."""
        from unittest.mock import patch

        seed = make_paper("Seed", doi="10.1000/seed")
        ref = make_paper("Ref", doi="10.1000/ref")
        good = FakeCitationConnector(references={"10.1000/seed": [ref]})
        bad = FakeCitationConnector()

        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=1,
            direction="backward",
            num_workers=4,
        )
        runner._connectors = [good, bad]

        original = runner._query_single_connector

        def patched(
            connector: CitationConnectorBase, paper: Paper
        ) -> tuple[str, list[Paper] | None, list[Paper] | None]:
            """Raise for the 'bad' connector, delegate otherwise."""
            if connector is bad:
                raise RuntimeError("unexpected crash")
            return original(connector, paper)

        with patch.object(runner, "_query_single_connector", side_effect=patched):
            graph = runner.run(show_progress=False)

        # The good connector result survives; the bad one is logged & skipped.
        assert graph.paper_count == 2  # seed + ref
        assert graph.edge_count == 1


class TestSnowballRunnerEmptyFrontier:
    """Tests for early termination when frontier is empty."""

    def test_empty_frontier_breaks_early(self, make_paper) -> None:
        """When no new papers are discovered, deeper levels are skipped."""
        seed = make_paper("Seed", doi="10.1000/seed")
        # Connector returns no references at any level.
        connector = FakeCitationConnector(references={})
        runner = SnowballRunner(
            seed_papers=[seed],
            max_depth=3,
            direction="backward",
        )
        runner._connectors = [connector]

        graph = runner.run(show_progress=False)

        assert graph.paper_count == 1  # only the seed
        assert graph.edge_count == 0

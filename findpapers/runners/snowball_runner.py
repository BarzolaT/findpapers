"""SnowballRunner: build a citation graph via forward/backward snowballing.

Given one or more seed papers, this runner iteratively fetches their
references (backward) and citing papers (forward) up to a configurable
depth, producing a :class:`~findpapers.core.citation_graph.CitationGraph`.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Literal

from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.connectors.crossref import CrossRefConnector
from findpapers.connectors.openalex import OpenAlexConnector
from findpapers.connectors.semantic_scholar import SemanticScholarConnector
from findpapers.core.citation_graph import CitationGraph
from findpapers.core.paper import Paper
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)


class SnowballRunner:
    """Build a citation graph around seed papers via iterative snowballing.

    The runner traverses the citation network in a BFS fashion: at each
    depth level it collects references and/or citing papers for every paper
    in the current frontier, adds the new papers as nodes to the graph, and
    records directed edges (``source`` → ``target`` meaning *source cites
    target*).

    Parameters
    ----------
    seed_papers : list[Paper] | Paper
        One or more papers to start the snowball from.  Papers without a
        DOI are silently skipped (they cannot be resolved by the APIs).
    depth : int
        Maximum number of snowball iterations.  ``1`` (the default)
        retrieves only the immediate neighbours of seed papers.
    direction : Literal["both", "backward", "forward"]
        ``"backward"`` fetches references (papers cited *by* the seed),
        ``"forward"`` fetches citing papers (papers that *cite* the seed),
        ``"both"`` fetches in both directions.
    openalex_api_key : str | None
        OpenAlex API key.
    email : str | None
        Contact email for polite-pool access (OpenAlex, CrossRef).
    semantic_scholar_api_key : str | None
        Semantic Scholar API key.
    num_workers : int
        Maximum number of connectors to query in parallel for each paper.
        Defaults to ``1`` (sequential).  The effective parallelism is
        capped at the number of available connectors.
    """

    def __init__(
        self,
        seed_papers: list[Paper] | Paper,
        *,
        depth: int = 1,
        direction: Literal["both", "backward", "forward"] = "both",
        openalex_api_key: str | None = None,
        email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        num_workers: int = 1,
    ) -> None:
        """Initialise snowball configuration without executing it."""
        if isinstance(seed_papers, Paper):
            seed_papers = [seed_papers]

        self._seed_papers = [p for p in seed_papers if p.doi]
        self._skipped_seeds = len(seed_papers) - len(self._seed_papers)
        self._depth = max(depth, 0)
        self._direction = direction
        self._num_workers = max(num_workers, 1)
        self._email = email
        self._graph: CitationGraph | None = None
        self._metrics: dict[str, int | float] = {}

        self._connectors = self._build_connectors(
            openalex_api_key=openalex_api_key,
            email=email,
            semantic_scholar_api_key=semantic_scholar_api_key,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False, show_progress: bool = True) -> CitationGraph:
        """Execute the snowball and return the citation graph.

        Can be called multiple times; each call resets previous results.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging.
        show_progress : bool
            When ``True`` (default), display tqdm progress bars for each
            snowball level while papers are being expanded.  Set to
            ``False`` to suppress progress output (e.g. in non-interactive
            environments or to keep log output clean).

        Returns
        -------
        CitationGraph
            The built citation graph.
        """
        if verbose:
            configure_verbose_logging()
            logger.info("=== SnowballRunner Configuration ===")
            logger.info(
                "Seed papers: %d (skipped %d without DOI)",
                len(self._seed_papers),
                self._skipped_seeds,
            )
            logger.info("Depth: %d", self._depth)
            logger.info("Direction: %s", self._direction)
            logger.info("Connectors: %s", [c.name for c in self._connectors])
            logger.info("Num workers: %d", self._num_workers)
            logger.info("=====================================")

        start = perf_counter()

        graph = CitationGraph(
            seed_papers=self._seed_papers,
            depth=self._depth,
            direction=self._direction,
        )

        frontier = list(self._seed_papers)

        try:
            for level in range(1, self._depth + 1):
                if not frontier:
                    break

                if verbose:
                    logger.info(
                        "Level %d/%d: processing %d papers.",
                        level,
                        self._depth,
                        len(frontier),
                    )

                next_frontier: list[Paper] = []

                with make_progress_bar(
                    desc=f"Level {level}/{self._depth}",
                    total=len(frontier),
                    unit="paper",
                    disable=not show_progress,
                ) as pbar:
                    for paper in frontier:
                        discovered = self._expand_paper(paper, graph, level)
                        next_frontier.extend(discovered)
                        pbar.update(1)

                frontier = next_frontier

                if verbose:
                    logger.info(
                        "Level %d/%d complete: %d new papers discovered.",
                        level,
                        self._depth,
                        len(next_frontier),
                    )
        finally:
            for connector in self._connectors:
                connector.close()

        elapsed = perf_counter() - start
        self._metrics = {
            "seed_papers": len(self._seed_papers),
            "skipped_seeds_without_doi": self._skipped_seeds,
            "depth": self._depth,
            "total_papers": graph.paper_count,
            "total_edges": graph.edge_count,
            "runtime_in_seconds": elapsed,
        }
        self._graph = graph

        if verbose:
            logger.info("=== Snowball Results ===")
            logger.info("Total papers: %d", graph.paper_count)
            logger.info("Total edges: %d", graph.edge_count)
            logger.info("Runtime: %.2f s", elapsed)
            logger.info("========================")

        return graph

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_connectors(
        self,
        *,
        openalex_api_key: str | None,
        email: str | None,
        semantic_scholar_api_key: str | None,
    ) -> list[CitationConnectorBase]:
        """Build all available citation connectors.

        Parameters
        ----------
        openalex_api_key : str | None
            OpenAlex API key.
        email : str | None
            Contact email.
        semantic_scholar_api_key : str | None
            Semantic Scholar API key.

        Returns
        -------
        list[CitationConnectorBase]
            Available citation connectors.
        """
        connectors: list[CitationConnectorBase] = []

        openalex = OpenAlexConnector(
            api_key=openalex_api_key,
            email=email,
        )
        connectors.append(openalex)

        semantic_scholar = SemanticScholarConnector(
            api_key=semantic_scholar_api_key,
        )
        connectors.append(semantic_scholar)

        crossref = CrossRefConnector(email=email)
        connectors.append(crossref)

        return connectors

    def _expand_paper(
        self,
        paper: Paper,
        graph: CitationGraph,
        level: int,
    ) -> list[Paper]:
        """Expand one paper by fetching its references and/or citing papers.

        For each connector, fetches backward and/or forward citations,
        adds new papers to the graph and records edges.

        Parameters
        ----------
        paper : Paper
            The paper to expand.
        graph : CitationGraph
            The graph under construction.
        level : int
            Current BFS depth level.

        Returns
        -------
        list[Paper]
            Newly discovered papers (not previously in the graph) that
            should be expanded in the next level.
        """
        new_papers: list[Paper] = []

        # Collect results from each connector — either sequentially or in
        # parallel depending on num_workers.
        connector_results = self._query_connectors(paper)

        for connector_name, references, citing in connector_results:
            # Backward: paper cites these references
            if references is not None:
                for ref_paper in references:
                    is_new = not graph.contains(ref_paper)
                    canonical = graph.add_paper(ref_paper, depth=level)
                    graph.add_edge(paper, canonical)
                    if is_new:
                        new_papers.append(canonical)

            # Forward: these papers cite the paper
            if citing is not None:
                for citing_paper in citing:
                    is_new = not graph.contains(citing_paper)
                    canonical = graph.add_paper(citing_paper, depth=level)
                    graph.add_edge(canonical, paper)
                    if is_new:
                        new_papers.append(canonical)

        return new_papers

    def _query_single_connector(
        self,
        connector: CitationConnectorBase,
        paper: Paper,
    ) -> tuple[str, list[Paper] | None, list[Paper] | None]:
        """Query a single connector for references and/or citing papers.

        Parameters
        ----------
        connector : CitationConnectorBase
            The connector to query.
        paper : Paper
            The paper to look up.

        Returns
        -------
        tuple[str, list[Paper] | None, list[Paper] | None]
            A ``(connector_name, references, citing)`` tuple.  Either list
            may be ``None`` if the corresponding direction was not requested.
        """
        references: list[Paper] | None = None
        citing: list[Paper] | None = None

        if self._direction in ("both", "backward"):
            try:
                references = connector.fetch_references(paper)
            except Exception:
                logger.warning(
                    "Error fetching references from %s for '%s'.",
                    connector.name,
                    paper.title,
                )
                references = []

        if self._direction in ("both", "forward"):
            try:
                citing = connector.fetch_cited_by(paper)
            except Exception:
                logger.warning(
                    "Error fetching cited-by from %s for '%s'.",
                    connector.name,
                    paper.title,
                )
                citing = []

        return connector.name, references, citing

    def _query_connectors(
        self,
        paper: Paper,
    ) -> list[tuple[str, list[Paper] | None, list[Paper] | None]]:
        """Query all connectors, optionally in parallel.

        When ``num_workers`` is 1 the connectors are called sequentially.
        Otherwise up to ``num_workers`` connectors are queried concurrently
        using a thread pool.

        Parameters
        ----------
        paper : Paper
            The paper to look up.

        Returns
        -------
        list[tuple[str, list[Paper] | None, list[Paper] | None]]
            Results from each connector.
        """
        if self._num_workers <= 1:
            return [
                self._query_single_connector(connector, paper) for connector in self._connectors
            ]

        results: list[tuple[str, list[Paper] | None, list[Paper] | None]] = []
        max_workers = min(self._num_workers, len(self._connectors))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._query_single_connector, connector, paper): connector
                for connector in self._connectors
            }
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    connector = futures[future]
                    logger.warning(
                        "Unexpected error querying %s for '%s'.",
                        connector.name,
                        paper.title,
                    )
        return results

"""SnowballRunner: build a citation graph via forward/backward snowballing.

Given one or more seed papers, this runner iteratively fetches their
references (backward) and citing papers (forward) up to a configurable
depth, producing a :class:`~findpapers.core.citation_graph.CitationGraph`.
"""

from __future__ import annotations

import contextlib
import datetime
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import perf_counter
from typing import Literal

from tqdm import tqdm

from findpapers.connectors import CITATION_REGISTRY
from findpapers.connectors.citation_base import CitationConnectorBase
from findpapers.core.citation_graph import CitationGraph
from findpapers.core.paper import Database, Paper
from findpapers.exceptions import InvalidParameterError
from findpapers.runners.base_runner import BaseRunner
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)


class SnowballRunner(BaseRunner):
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
    max_depth : int
        Maximum number of snowball iterations.  ``1`` (the default)
        retrieves only the immediate neighbours of seed papers.
    direction : Literal["both", "backward", "forward"]
        ``"backward"`` fetches references (papers cited *by* the seed),
        ``"forward"`` fetches citing papers (papers that *cite* the seed),
        ``"both"`` fetches in both directions.
    top_n_per_level : int | None
        When set, only the *top N* most-cited papers discovered at each
        snowball level are kept as candidates for expansion in the next
        level.  Seed papers are always expanded regardless of this limit.
        This is useful for controlling cost when running deep snowballs:
        setting a small value (e.g. ``20``) avoids the combinatorial
        explosion that occurs without a cut-off.  When ``None`` (default)
        all discovered papers are expanded.
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
    since : datetime.date | None
        Only include discovered papers published on or after this date.
        Seed papers are never filtered.  ``None`` (default) disables
        the lower-bound date filter.
    until : datetime.date | None
        Only include discovered papers published on or before this date.
        Seed papers are never filtered.  ``None`` (default) disables
        the upper-bound date filter.
    """

    def __init__(
        self,
        seed_papers: list[Paper] | Paper,
        *,
        max_depth: int = 1,
        direction: Literal["both", "backward", "forward"] = "both",
        top_n_per_level: int | None = None,
        openalex_api_key: str | None = None,
        email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        num_workers: int = 1,
        since: datetime.date | None = None,
        until: datetime.date | None = None,
    ) -> None:
        """Initialise snowball configuration without executing it.

        Raises
        ------
        InvalidParameterError
            If *max_depth* is less than 1 or *top_n_per_level* is less than 1.
        """
        if max_depth < 1:
            raise InvalidParameterError(f"max_depth must be >= 1, got {max_depth}")
        if top_n_per_level is not None and top_n_per_level < 1:
            raise InvalidParameterError(
                f"top_n_per_level must be >= 1 when set, got {top_n_per_level}"
            )

        super().__init__(since=since, until=until)

        if isinstance(seed_papers, Paper):
            seed_papers = [seed_papers]

        self._seed_papers = [p for p in seed_papers if p.doi]
        self._skipped_seeds = len(seed_papers) - len(self._seed_papers)
        self._max_depth = max_depth
        self._direction = direction
        self._top_n_per_level = top_n_per_level
        self._num_workers = max(num_workers, 1)
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
            logger.info("Max depth: %d", self._max_depth)
            logger.info("Direction: %s", self._direction)
            logger.info(
                "Top N per level: %s",
                str(self._top_n_per_level) if self._top_n_per_level else "unlimited",
            )
            logger.info("Connectors: %s", [c.name for c in self._connectors])
            logger.info("Num workers: %d", self._num_workers)
            logger.info("=====================================")

        start = perf_counter()

        graph = CitationGraph(
            seed_papers=self._seed_papers,
            max_depth=self._max_depth,
            direction=self._direction,
        )

        frontier = list(self._seed_papers)

        # Create a single ThreadPoolExecutor for the entire run to avoid
        # the overhead of creating/destroying one per paper.  When
        # num_workers <= 1 connectors are called sequentially, so no pool
        # is needed.
        use_pool = self._num_workers > 1 and len(self._connectors) > 1
        pool: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=min(self._num_workers, len(self._connectors)))
            if use_pool
            else None
        )

        try:
            for level in range(1, self._max_depth + 1):
                if not frontier:
                    break

                if verbose:
                    logger.info(
                        "Level %d/%d: processing %d papers.",
                        level,
                        self._max_depth,
                        len(frontier),
                    )

                next_frontier: list[Paper] = []

                with make_progress_bar(
                    desc=f"Level {level}/{self._max_depth}",
                    total=len(frontier),
                    unit="paper",
                    disable=not show_progress,
                ) as pbar:
                    if self._top_n_per_level is None:
                        # No limit: add every discovered paper to the graph.
                        for paper in frontier:
                            discovered = self._expand_paper(
                                paper, graph, pool, show_progress=show_progress
                            )
                            next_frontier.extend(discovered)
                            pbar.update(1)
                    else:
                        # Collect all candidates from the whole frontier
                        # WITHOUT adding them to the graph so we can rank
                        # and filter before committing anything.
                        all_raw: list[tuple[Paper, Paper, bool]] = []
                        for paper in frontier:
                            all_raw.extend(
                                self._collect_candidates(paper, pool, show_progress=show_progress)
                            )
                            pbar.update(1)

                        # Group novel candidates by graph key.
                        # For duplicates, keep the representation with the
                        # highest known citation count (for ranking) and
                        # accumulate all (source, is_ref) edge tuples.
                        best: dict[str, Paper] = {}
                        edge_map: dict[str, list[tuple[Paper, bool]]] = {}
                        for candidate, source, is_ref in all_raw:
                            key = CitationGraph._paper_key(candidate)
                            if key is None or graph.contains(candidate):
                                continue
                            if not self._matches_filters(candidate):
                                continue
                            if key not in best:
                                best[key] = candidate
                                edge_map[key] = []
                            elif candidate.citations is not None and (
                                best[key].citations is None
                                or candidate.citations > (best[key].citations or 0)
                            ):
                                best[key] = candidate
                            edge_map[key].append((source, is_ref))

                        # Rank by citation count descending and take top N.
                        top_keys = sorted(
                            best,
                            key=lambda k: best[k].citations or 0,
                            reverse=True,
                        )[: self._top_n_per_level]

                        # Add only the top-N papers to the graph.
                        for key in top_keys:
                            paper_repr = best[key]
                            first_source = edge_map[key][0][0]
                            canonical = graph.add_node(paper_repr, discovered_from=first_source)
                            for source, is_ref in edge_map[key]:
                                if is_ref:
                                    graph.add_edge(source, canonical)
                                else:
                                    graph.add_edge(canonical, source)
                            next_frontier.append(canonical)

                frontier = next_frontier

                if verbose:
                    logger.info(
                        "Level %d/%d complete: %d new papers discovered%s.",
                        level,
                        self._max_depth,
                        len(next_frontier),
                        f" (top {self._top_n_per_level} kept)" if self._top_n_per_level else "",
                    )
        finally:
            if pool is not None:
                pool.shutdown(wait=True)
            for connector in self._connectors:
                connector.close()

        elapsed = perf_counter() - start
        self._metrics = {
            "seed_papers": len(self._seed_papers),
            "skipped_seeds_without_doi": self._skipped_seeds,
            "max_depth": self._max_depth,
            "total_nodes": graph.node_count,
            "total_edges": graph.edge_count,
            "runtime_in_seconds": elapsed,
        }
        self._graph = graph

        if verbose:
            logger.info("=== Snowball Results ===")
            logger.info("Total nodes: %d", graph.node_count)
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
        # Per-connector constructor credentials.  Connectors with no entry
        # are constructed with no arguments.  The classes are looked up in
        # the central CITATION_REGISTRY so that this runner does not need
        # to import every concrete connector.
        _credentials: dict[Database, dict[str, str | None]] = {
            Database.OPENALEX: {"api_key": openalex_api_key, "email": email},
            Database.SEMANTIC_SCHOLAR: {"api_key": semantic_scholar_api_key},
            Database.CROSSREF: {"email": email},
        }

        return [cls(**_credentials.get(name, {})) for name, cls in CITATION_REGISTRY.items()]

    def _expand_paper(
        self,
        paper: Paper,
        graph: CitationGraph,
        pool: ThreadPoolExecutor | None = None,
        *,
        show_progress: bool = True,
    ) -> list[Paper]:
        """Expand one paper by fetching its references and/or citing papers.

        For each connector, fetches backward and/or forward citations,
        adds new papers to the graph and records edges.  The depth of
        discovered papers is automatically derived from the depth of
        *paper* in the graph.

        Parameters
        ----------
        paper : Paper
            The paper to expand.
        graph : CitationGraph
            The graph under construction.
        pool : ThreadPoolExecutor | None
            Optional shared thread pool for parallel connector queries.
            When ``None``, connectors are called sequentially.
        show_progress : bool
            When ``True``, display per-connector progress bars for
            long pagination operations.

        Returns
        -------
        list[Paper]
            Newly discovered papers (not previously in the graph) that
            should be expanded in the next level.
        """
        new_papers: list[Paper] = []

        for candidate, source, is_ref in self._collect_candidates(
            paper, pool, show_progress=show_progress
        ):
            if not self._matches_filters(candidate):
                continue
            is_new = not graph.contains(candidate)
            canonical = graph.add_node(candidate, discovered_from=source)
            if is_ref:
                graph.add_edge(source, canonical)
            else:
                graph.add_edge(canonical, source)
            if is_new:
                new_papers.append(canonical)

        return new_papers

    def _collect_candidates(
        self,
        paper: Paper,
        pool: ThreadPoolExecutor | None = None,
        *,
        show_progress: bool = True,
    ) -> list[tuple[Paper, Paper, bool]]:
        """Query connectors for *paper* and return raw candidates without modifying the graph.

        Parameters
        ----------
        paper : Paper
            The paper to query.
        pool : ThreadPoolExecutor | None
            Optional shared thread pool for parallel connector queries.
        show_progress : bool
            Display per-connector progress bars.

        Returns
        -------
        list[tuple[Paper, Paper, bool]]
            Each entry is ``(candidate, source, is_reference)``.  *is_reference*
            is ``True`` for backward citations (source cites candidate) and
            ``False`` for forward citations (candidate cites source).
        """
        candidates: list[tuple[Paper, Paper, bool]] = []

        for _name, references, citing in self._query_connectors(
            paper, pool, show_progress=show_progress
        ):
            if references is not None:
                for ref_paper in references:
                    candidates.append((ref_paper, paper, True))
            if citing is not None:
                for citing_paper in citing:
                    candidates.append((citing_paper, paper, False))

        return candidates

    def _query_single_connector(
        self,
        connector: CitationConnectorBase,
        paper: Paper,
        *,
        show_progress: bool = True,
        parallel: bool = False,
    ) -> tuple[str, list[Paper] | None, list[Paper] | None]:
        """Query a single connector for references and/or citing papers.

        When *show_progress* is ``True``, a nested tqdm progress bar is
        created for each fetch direction using the expected total from
        :meth:`~CitationConnectorBase.get_expected_counts`.

        Parameters
        ----------
        connector : CitationConnectorBase
            The connector to query.
        paper : Paper
            The paper to look up.
        show_progress : bool
            Display per-connector progress bars for long pagination.
        parallel : bool
            When ``True``, the connector is being called from a thread pool.
            Inner progress bars are disabled in this case to avoid
            interleaved output across threads.

        Returns
        -------
        tuple[str, list[Paper] | None, list[Paper] | None]
            A ``(connector_name, references, citing)`` tuple.  Either list
            may be ``None`` if the corresponding direction was not requested.
        """
        references: list[Paper] | None = None
        citing: list[Paper] | None = None

        def _pbar_callback(pbar: tqdm) -> Callable[[int], None]:
            """Return a typed callback wrapping ``pbar.update``."""

            def _cb(n: int) -> None:
                pbar.update(n)

            return _cb

        # Inner bars are disabled when running in parallel (multiple threads
        # would interleave writes and garble the terminal output).
        inner_show = show_progress and not parallel

        # Fetch expected counts for determinate progress bars.
        cit_count: int | None = None
        ref_count: int | None = None
        if inner_show:
            with contextlib.suppress(Exception):
                cit_count, ref_count = connector.get_expected_counts(paper)

        if self._direction in ("both", "backward"):
            try:
                with make_progress_bar(
                    desc=f"  {connector.name} backward",
                    total=ref_count,
                    unit="paper",
                    disable=not inner_show,
                    leave=False,
                ) as pbar:
                    references = connector.fetch_references(
                        paper,
                        progress_callback=_pbar_callback(pbar),
                    )
            except Exception:
                logger.warning(
                    "Error fetching references from %s for '%s'.",
                    connector.name,
                    paper.title,
                )
                references = []

        if self._direction in ("both", "forward"):
            try:
                with make_progress_bar(
                    desc=f"  {connector.name} forward",
                    total=cit_count,
                    unit="paper",
                    disable=not inner_show,
                    leave=False,
                ) as pbar:
                    citing = connector.fetch_cited_by(
                        paper,
                        progress_callback=_pbar_callback(pbar),
                    )
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
        pool: ThreadPoolExecutor | None = None,
        *,
        show_progress: bool = True,
    ) -> list[tuple[str, list[Paper] | None, list[Paper] | None]]:
        """Query all connectors, optionally in parallel.

        When *pool* is ``None`` the connectors are called sequentially.
        Otherwise connectors are queried concurrently using the shared
        thread pool.

        Parameters
        ----------
        paper : Paper
            The paper to look up.
        pool : ThreadPoolExecutor | None
            Optional shared thread pool.  When ``None``, connectors are
            called sequentially.
        show_progress : bool
            Display per-connector progress bars.

        Returns
        -------
        list[tuple[str, list[Paper] | None, list[Paper] | None]]
            Results from each connector.
        """
        if pool is None:
            return [
                self._query_single_connector(
                    connector,
                    paper,
                    show_progress=show_progress,
                )
                for connector in self._connectors
            ]

        results: list[tuple[str, list[Paper] | None, list[Paper] | None]] = []
        futures = {
            pool.submit(
                self._query_single_connector,
                connector,
                paper,
                show_progress=show_progress,
                parallel=True,
            ): connector
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

"""EnrichmentRunner: enriches a list of papers from web page metadata."""

from __future__ import annotations

import logging
from time import perf_counter

from findpapers.core.paper import Paper
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.utils.enrichment import enrich_from_sources
from findpapers.utils.parallel import execute_tasks
from findpapers.utils.predatory import is_predatory_publication

logger = logging.getLogger(__name__)


class EnrichmentRunner:
    """Runner that enriches a provided list of papers using web scraping.

    For each paper, the runner attempts to fetch metadata from the paper's
    known URLs and merges any found data into the paper object using the
    most-complete strategy.

    Parameters
    ----------
    papers : list[Paper]
        Papers to enrich.
    num_workers : int
        Number of parallel workers.  Defaults to ``1``, which runs
        sequentially.  Values greater than ``1`` enable parallel execution.
    timeout : float | None
        Per-request and global timeout in seconds.

    Examples
    --------
    >>> runner = EnrichmentRunner(papers=papers, num_workers=4, timeout=15.0)
    >>> runner.run(verbose=True)
    >>> metrics = runner.get_metrics()
    """

    def __init__(
        self,
        papers: list[Paper],
        num_workers: int = 1,
        timeout: float | None = 10.0,
    ) -> None:
        """Initialise enrichment configuration without executing it."""
        self._executed = False
        self._results = list(papers)
        self._metrics: dict[str, int | float] = {}
        self._num_workers = num_workers
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False) -> None:
        """Enrich all configured papers in-place.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.

        Returns
        -------
        None
        """
        if verbose:
            logging.getLogger().setLevel(logging.INFO)
            logger.info("=== EnrichmentRunner Configuration ===")
            logger.info("Total papers: %d", len(self._results))
            logger.info("Num workers: %d", self._num_workers)
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("======================================")

        start = perf_counter()
        metrics: dict[str, int | float] = {
            "total_papers": len(self._results),
            "runtime_in_seconds": 0.0,
            "enriched_papers": 0,
        }

        self._enrich_results(metrics, verbose)

        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics
        self._executed = True

        if verbose:
            logger.info("=== Enrichment Summary ===")
            logger.info("Total papers: %d", int(metrics["total_papers"]))
            logger.info("Enriched: %d", int(metrics["enriched_papers"]))
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            logger.info("==========================")

    def get_metrics(self) -> dict[str, int | float]:
        """Return a snapshot of numeric performance metrics.

        Returns
        -------
        dict[str, int | float]
            Metrics with at least ``total_papers``, ``enriched_papers``, and
            ``runtime_in_seconds``.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_executed(self) -> None:
        """Raise if :meth:`run` has not been called.

        Raises
        ------
        SearchRunnerNotExecutedError
            When the runner has not been executed.
        """
        if not self._executed:
            raise SearchRunnerNotExecutedError("EnrichmentRunner has not been executed yet.")

    def _enrich_results(self, metrics: dict[str, int | float], verbose: bool = False) -> None:
        """Enrich all papers and update metrics.

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict to update in-place.
        verbose : bool
            Enable verbose logging.

        Returns
        -------
        None
        """
        if not self._results:
            return

        num_workers = self._num_workers
        timeout = self._timeout
        enriched = 0

        def _enrich_task(paper: Paper) -> bool:
            return self._enrich_paper(paper, timeout=timeout)

        for _paper, result, error in execute_tasks(
            self._results,
            _enrich_task,
            num_workers=num_workers,
            timeout=timeout,
            progress_total=len(self._results),
            progress_unit="paper",
            progress_desc="Enriching",
            use_progress=True,
            stop_on_timeout=True,
        ):
            if error is not None:
                if verbose:
                    logger.warning("Error enriching paper: %s", error)
                continue
            if result:
                enriched += 1

        metrics["enriched_papers"] = enriched

    def _enrich_paper(self, paper: Paper, timeout: float | None = None) -> bool:
        """Attempt to enrich a single paper using its known URLs.

        Parameters
        ----------
        paper : Paper
            Paper to enrich.
        timeout : float | None
            HTTP request timeout in seconds.

        Returns
        -------
        bool
            ``True`` if the paper was successfully enriched.
        """
        all_urls = [u for u in [paper.url, paper.pdf_url] if u]
        if not all_urls:
            return False
        enriched = enrich_from_sources(urls=all_urls, timeout=timeout)
        if enriched is None:
            return False
        paper.merge(enriched)
        # Re-evaluate the predatory flag: the publication may have been
        # populated only after enrichment, so the original flag (set during
        # the search phase) might be stale.
        if paper.publication is not None:
            paper.publication.is_potentially_predatory = is_predatory_publication(paper.publication)
        return True

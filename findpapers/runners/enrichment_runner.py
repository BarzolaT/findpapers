"""EnrichmentRunner: enriches a list of papers from web page metadata."""

from __future__ import annotations

import logging
from enum import Enum
from time import perf_counter

from findpapers.connectors.crossref import CrossRefConnector
from findpapers.core.paper import Paper
from findpapers.utils.enrichment import build_paper_from_metadata, fetch_metadata
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.parallel import execute_tasks

logger = logging.getLogger(__name__)


class EnrichmentOutcome(Enum):
    """Possible outcomes of enriching a single paper.

    Attributes
    ----------
    ENRICHED_DOI : str
        At least one field was updated, with CrossRef contributing data.
    ENRICHED : str
        At least one field was updated via URL scraping.
    NO_CHANGE : str
        Metadata was fetched but mirrored existing data.
    NO_METADATA : str
        URLs were reachable but returned no parseable metadata.
    FETCH_ERROR : str
        All sources raised HTTP/network errors.
    NO_URLS : str
        Paper has no usable URL and no DOI.
    """

    ENRICHED_DOI = "enriched+doi"
    ENRICHED = "enriched"
    NO_CHANGE = "no_change"
    NO_METADATA = "no_metadata"
    FETCH_ERROR = "fetch_error"
    NO_URLS = "no_urls"


def _enrichment_snapshot(paper: Paper) -> tuple:
    """Return a tuple of enrichable fields for change-detection.

    The tuple covers every field that :func:`~findpapers.utils.enrichment.fetch_metadata`
    can populate so that ``_enrich_paper`` can tell whether a merge actually improved the
    paper rather than just confirming data that was already present.

    Parameters
    ----------
    paper : Paper
        Paper to snapshot.

    Returns
    -------
    tuple
        Immutable snapshot of enrichable fields.
    """
    return (
        paper.abstract,
        paper.doi,
        paper.pdf_url,
        paper.publication_date,
        paper.page_range,
        paper.page_count,
        paper.citations,
        frozenset(paper.authors or []),
        frozenset(paper.keywords or []),
        paper.source.title if paper.source else None,
        paper.source.publisher if paper.source else None,
        paper.source.issn if paper.source else None,
        paper.source.isbn if paper.source else None,
        paper.source.source_type if paper.source else None,
    )


class EnrichmentRunner:
    """Runner that enriches a provided list of papers using web scraping.

    For each paper, the runner attempts to fetch metadata from the paper's
    known URLs and merges any found data into the paper object using the
    most-complete strategy.

    Parameters
    ----------
    papers : list[Paper]
        Papers to enrich.
    email : str | None
        Contact email for polite-pool access on CrossRef.  When provided
        CrossRef grants higher rate-limits.
    num_workers : int
        Number of parallel workers.  Defaults to ``1``, which runs
        sequentially.  Values greater than ``1`` enable parallel execution.
    timeout : float | None
        Per-request HTTP timeout in seconds.

    Examples
    --------
    >>> runner = EnrichmentRunner(papers=papers, num_workers=4, timeout=15.0)
    >>> metrics = runner.run(verbose=True)
    """

    def __init__(
        self,
        papers: list[Paper],
        email: str | None = None,
        num_workers: int = 1,
        timeout: float | None = 10.0,
    ) -> None:
        """Initialise enrichment configuration without executing it."""
        self._results = list(papers)
        self._metrics: dict[str, int | float] = {}
        self._num_workers = num_workers
        self._timeout = timeout
        self._crossref = CrossRefConnector(email=email)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False, show_progress: bool = True) -> dict[str, int | float]:
        """Enrich all configured papers in-place.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.
        show_progress : bool
            When ``True`` (default), display a tqdm progress bar while
            papers are being enriched.  Set to ``False`` to suppress
            progress output (e.g. in non-interactive environments or to
            keep log output clean).

        Returns
        -------
        dict[str, int | float]
            Metrics with at least ``total_papers``, ``enriched_papers``,
            and ``runtime_in_seconds``.
        """
        if verbose:
            configure_verbose_logging()
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
            "doi_enriched_papers": 0,
            "fetch_error_papers": 0,
            "no_metadata_papers": 0,
            "no_change_papers": 0,
            "no_urls_papers": 0,
        }

        try:
            self._enrich_results(metrics, verbose, show_progress=show_progress)
        finally:
            self._crossref.close()

        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics

        if verbose:
            logger.info("=== Enrichment Summary ===")
            logger.info("Total papers: %d", int(metrics["total_papers"]))
            logger.info("Enriched: %d", int(metrics["enriched_papers"]))
            logger.info("  via DOI (CrossRef): %d", int(metrics["doi_enriched_papers"]))
            logger.info("Fetch errors: %d", int(metrics["fetch_error_papers"]))
            logger.info("No metadata: %d", int(metrics["no_metadata_papers"]))
            logger.info("No change: %d", int(metrics["no_change_papers"]))
            logger.info("No URLs: %d", int(metrics["no_urls_papers"]))
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            logger.info("==========================")

        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _enrich_results(
        self,
        metrics: dict[str, int | float],
        verbose: bool = False,
        *,
        show_progress: bool = True,
    ) -> None:
        """Enrich all papers and update metrics.

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict to update in-place.
        verbose : bool
            Enable verbose logging.
        show_progress : bool
            Display tqdm progress bars.

        Returns
        -------
        None
        """
        if not self._results:
            return

        num_workers = self._num_workers
        timeout = self._timeout
        enriched = 0
        doi_enriched = 0
        fetch_errors = 0
        no_metadata = 0
        no_change = 0
        no_urls = 0

        def _enrich_task(paper: Paper) -> EnrichmentOutcome:
            return self._enrich_paper(paper, timeout=timeout)

        for _paper, result, error in execute_tasks(
            self._results,
            _enrich_task,
            num_workers=num_workers,
            timeout=None,
            progress_total=len(self._results),
            progress_unit="paper",
            progress_desc="Enriching",
            use_progress=show_progress,
        ):
            if error is not None:
                if verbose:
                    logger.warning("Error enriching paper: %s", error)
                fetch_errors += 1
                continue
            if result in (EnrichmentOutcome.ENRICHED, EnrichmentOutcome.ENRICHED_DOI):
                enriched += 1
                if result == EnrichmentOutcome.ENRICHED_DOI:
                    doi_enriched += 1
            elif result == EnrichmentOutcome.FETCH_ERROR:
                fetch_errors += 1
            elif result == EnrichmentOutcome.NO_METADATA:
                no_metadata += 1
            elif result == EnrichmentOutcome.NO_CHANGE:
                no_change += 1
            elif result == EnrichmentOutcome.NO_URLS:
                no_urls += 1

        metrics["enriched_papers"] = enriched
        metrics["doi_enriched_papers"] = doi_enriched
        metrics["fetch_error_papers"] = fetch_errors
        metrics["no_metadata_papers"] = no_metadata
        metrics["no_change_papers"] = no_change
        metrics["no_urls_papers"] = no_urls

    def _enrich_paper(self, paper: Paper, timeout: float | None = None) -> EnrichmentOutcome:
        """Attempt to enrich a single paper using the CrossRef API and URL scraping.

        The method first queries the CrossRef API when the paper has a DOI,
        since the API returns reliable structured metadata.  It then also
        tries URL-based HTML scraping to fill in any remaining gaps (e.g.
        PDF links, extra keywords).  Both results are merged into the paper.

        Parameters
        ----------
        paper : Paper
            Paper to enrich.
        timeout : float | None
            HTTP request timeout in seconds.

        Returns
        -------
        EnrichmentOutcome
            The outcome of the enrichment attempt.
        """
        before = _enrichment_snapshot(paper)
        doi_contributed = False

        # ------------------------------------------------------------------
        # Phase 1: CrossRef API (structured metadata via DOI)
        # ------------------------------------------------------------------
        if paper.doi:
            try:
                work = self._crossref.fetch_work(paper.doi)
                if work:
                    crossref_paper = self._crossref.build_paper(work)
                    if crossref_paper is not None:
                        mid = _enrichment_snapshot(paper)
                        paper.merge(crossref_paper)
                        if _enrichment_snapshot(paper) != mid:
                            doi_contributed = True
            except Exception:  # noqa: BLE001
                logger.debug("CrossRef fetch error for DOI: %s", paper.doi)

        # ------------------------------------------------------------------
        # Phase 2: URL-based HTML scraping
        # ------------------------------------------------------------------
        candidate_urls: list[str] = []
        if paper.url and "pdf" not in paper.url.lower():
            candidate_urls.append(paper.url)
        if paper.doi:
            candidate_urls.append(f"https://doi.org/{paper.doi}")
        if paper.pdf_url and "pdf" not in paper.pdf_url.lower():
            candidate_urls.append(paper.pdf_url)

        # Deduplicate while preserving insertion order.
        seen: set[str] = set()
        deduped: list[str] = []
        for u in candidate_urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)

        had_fetch_error = False
        had_url_metadata = False
        for url in deduped:
            try:
                metadata = fetch_metadata(url, timeout=timeout)
            except Exception:  # noqa: BLE001
                had_fetch_error = True
                logger.debug("Fetch error for enrichment URL: %s", url)
                continue
            if not metadata:
                continue
            enriched_paper = build_paper_from_metadata(metadata, url)
            if enriched_paper is None:
                continue
            had_url_metadata = True
            paper.merge(enriched_paper)
            break  # first successful URL scrape is sufficient

        # ------------------------------------------------------------------
        # Determine overall result
        # ------------------------------------------------------------------
        changed = _enrichment_snapshot(paper) != before

        if not paper.doi and not deduped:
            return EnrichmentOutcome.NO_URLS
        if changed:
            return EnrichmentOutcome.ENRICHED_DOI if doi_contributed else EnrichmentOutcome.ENRICHED
        # Nothing changed from here on — classify the reason.
        if had_url_metadata or doi_contributed:
            # Sources returned data but it mirrored what we already had.
            return EnrichmentOutcome.NO_CHANGE
        if had_fetch_error and not paper.doi:
            return EnrichmentOutcome.FETCH_ERROR
        if deduped and not had_fetch_error and not had_url_metadata:
            # URLs were reachable but returned no parseable metadata.
            return EnrichmentOutcome.NO_METADATA
        return EnrichmentOutcome.NO_CHANGE

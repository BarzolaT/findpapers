"""SearchRunner: the main entry point for performing academic paper searches."""

from __future__ import annotations

import datetime as dt
import logging
from datetime import UTC, datetime
from time import perf_counter

from findpapers.connectors import SEARCH_REGISTRY
from findpapers.connectors.search_base import SearchConnectorBase
from findpapers.core.paper import Database, Paper
from findpapers.core.search_result import SearchResult
from findpapers.exceptions import InvalidParameterError, MissingApiKeyError, UnsupportedQueryError
from findpapers.query.parser import QueryParser
from findpapers.query.propagator import FilterPropagator
from findpapers.query.validator import QueryValidator
from findpapers.runners.discovery_runner import DEFAULT_ENRICHMENT_DATABASES, DiscoveryRunner
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.parallel import execute_tasks
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)


class SearchRunner(DiscoveryRunner):
    """Public API entry point for running academic paper searches.

    The runner orchestrates the full pipeline:

    1. Parse and validate the query string.
    2. Fetch papers from each configured database searcher.
    3. Deduplicate and merge results using a two-pass strategy: first by
       DOI when available, then a second pass by normalised title+year to
       catch cross-database cases where the same paper carries different DOIs
       (e.g. arXiv preprint DOI vs. publisher DOI).
    Parameters
    ----------
    query : str
        Raw query string (e.g. ``"ti[machine learning] AND abs[deep learning]"``).
    databases : list[str] | None
        Database identifiers to query.  When ``None`` all supported databases
        are used.  Supported values: ``"arxiv"``, ``"ieee"``, ``"openalex"``,
        ``"pubmed"``, ``"scopus"``, ``"semantic_scholar"``, ``"wos"``.
    max_papers_per_database : int | None
        Maximum papers to retrieve from each database.  ``None`` means
        unlimited.
    ieee_api_key : str | None
        IEEE Xplore API key.
    scopus_api_key : str | None
        Elsevier / Scopus API key.
    pubmed_api_key : str | None
        NCBI PubMed API key (increases rate limit).
    openalex_api_key : str | None
        OpenAlex API key.
    email : str | None
        Contact email for polite-pool access (OpenAlex, CrossRef).
    semantic_scholar_api_key : str | None
        Semantic Scholar API key (increases rate limit).
    wos_api_key : str | None
        Clarivate Web of Science API key.
    num_workers : int
        Number of parallel workers for running database searchers
        concurrently.  Defaults to ``1``, which runs all searchers
        sequentially.  Values greater than ``1`` enable parallel execution.
    since : dt.date | None
        Only return papers published on or after this date.
    until : dt.date | None
        Only return papers published on or before this date.
    enrichment_databases : list[str] | None
        Databases used to enrich papers after search and filtering.
        ``None`` (default) runs enrichment against ``crossref`` and
        ``web_scraping``, which covers the majority of metadata gaps without
        consuming quota from rate-limited databases.  Pass a list to enable
        additional sources (``"arxiv"``, ``"ieee"``, ``"openalex"``,
        ``"pubmed"``, ``"scopus"``, ``"semantic_scholar"``).
        Pass ``[]`` to disable enrichment entirely.
    proxy : str | None
        Optional HTTP/HTTPS proxy URL forwarded to the enrichment
        :class:`~findpapers.runners.get_runner.GetRunner`.
    ssl_verify : bool
        Whether to verify SSL certificates during enrichment.
        Defaults to ``True``.

    Raises
    ------
    findpapers.exceptions.QueryValidationError
        If the query string fails validation.
    findpapers.exceptions.InvalidParameterError
        If *enrichment_databases* contains unknown database names.

    Examples
    --------
    >>> runner = SearchRunner(
    ...     query="ti[machine learning] AND abs[neural network]",
    ...     databases=["arxiv", "pubmed"],
    ...     max_papers_per_database=50,
    ... )
    >>> result = runner.run()
    >>> papers = result.papers
    """

    def __init__(
        self,
        query: str,
        databases: list[str] | None = None,
        max_papers_per_database: int | None = None,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        wos_api_key: str | None = None,
        num_workers: int = 1,
        since: dt.date | None = None,
        until: dt.date | None = None,
        enrichment_databases: list[str] | None = DEFAULT_ENRICHMENT_DATABASES,
        proxy: str | None = None,
        ssl_verify: bool = True,
    ) -> None:
        """Initialise search configuration without executing it.

        Parameters
        ----------
        query : str
            Raw query string.
        databases : list[str] | None
            Database identifiers to query.  ``None`` selects all available.
        max_papers_per_database : int | None
            Maximum papers per database.  ``None`` means no limit.
        ieee_api_key : str | None
            IEEE Xplore API key.
        scopus_api_key : str | None
            Elsevier / Scopus API key.
        pubmed_api_key : str | None
            NCBI PubMed API key.
        openalex_api_key : str | None
            OpenAlex API key.
        email : str | None
            Contact email for polite-pool access (CrossRef, OpenAlex).
        semantic_scholar_api_key : str | None
            Semantic Scholar API key.
        wos_api_key : str | None
            Clarivate Web of Science API key.
        num_workers : int
            Number of parallel workers.  Defaults to ``1``.
        since : dt.date | None
            Lower-bound publication date filter.
        until : dt.date | None
            Upper-bound publication date filter.
        enrichment_databases : list[str] | None
            Databases for post-search enrichment.  Defaults to
            ``DEFAULT_ENRICHMENT_DATABASES`` (``["crossref", "web_scraping"]``).
            Pass ``None`` or ``[]`` to disable enrichment entirely.
        proxy : str | None
            Optional HTTP/HTTPS proxy URL for enrichment requests.
        ssl_verify : bool
            Whether to verify SSL certificates during enrichment.

        Raises
        ------
        InvalidParameterError
            If *enrichment_databases* contains unknown database names.
        """
        self._results: list[Paper] = []
        self._metrics: dict[str, int | float] = {}
        self._search: SearchResult | None = None

        super().__init__(
            since=since,
            until=until,
            ieee_api_key=ieee_api_key,
            scopus_api_key=scopus_api_key,
            pubmed_api_key=pubmed_api_key,
            openalex_api_key=openalex_api_key,
            email=email,
            semantic_scholar_api_key=semantic_scholar_api_key,
            wos_api_key=wos_api_key,
            proxy=proxy,
            ssl_verify=ssl_verify,
            enrichment_databases=enrichment_databases,
        )

        self._query_string = query
        self._max_papers_per_database = max_papers_per_database
        self._num_workers = num_workers

        validator = QueryValidator()
        validator.validate(query)
        parser = QueryParser()
        self._query = parser.parse(query)

        # Propagate filter specifiers (e.g. ti, abs) through the query tree
        # so that group-level filters reach child term nodes.
        propagator = FilterPropagator()
        propagator.propagate(self._query)

        self._searchers, self._skipped_databases = self._build_searchers(
            databases=databases,
            ieee_api_key=ieee_api_key,
            scopus_api_key=scopus_api_key,
            pubmed_api_key=pubmed_api_key,
            openalex_api_key=openalex_api_key,
            email=email,
            semantic_scholar_api_key=semantic_scholar_api_key,
            wos_api_key=wos_api_key,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False, show_progress: bool = True) -> SearchResult:
        """Execute the configured pipeline and return the results.

        Can be called multiple times; each call resets previous results.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.
        show_progress : bool
            When ``True`` (default), display tqdm progress bars for each
            database while papers are being fetched.  Set to ``False``
            to suppress progress output (e.g. in non-interactive
            environments or to keep log output clean).

        Returns
        -------
        SearchResult
            Search result object containing papers and metadata.
        """
        _root_logger = logging.getLogger()
        _saved_log_level = _root_logger.level
        if verbose:
            configure_verbose_logging()
            logger.info("=== SearchRunner Configuration ===")
            logger.info("Databases: %s", [s.name for s in self._searchers])
            logger.info("Num workers: %d", self._num_workers)
            logger.info("Query: %s", self._query_string)
            logger.info("Max papers per database: %s", self._max_papers_per_database or "none")
            logger.info("==================================")

        start = perf_counter()
        self._results = []
        metrics: dict[str, int | float] = {
            "total_papers": 0,
            "runtime_in_seconds": 0.0,
        }
        for _skipped in self._skipped_databases:
            metrics[f"total_papers_from_{_skipped}"] = 0

        failed_databases: list[str] = []
        db_runtimes: dict[str, float] = {}
        try:
            failed_databases, db_runtimes = self._fetch_papers(
                metrics, verbose, show_progress=show_progress
            )
        finally:
            for searcher in self._searchers:
                searcher.close()

        self._search = SearchResult(
            query=self._query_string,
            max_papers_per_database=self._max_papers_per_database,
            processed_at=datetime.now(UTC),
            databases=[s.name for s in self._searchers],
            papers=list(self._results),
            runtime_seconds=None,
            runtime_seconds_per_database=db_runtimes or None,
            since=self._since,
            until=self._until,
            failed_databases=failed_databases or None,
        )
        before_dedupe = len(self._results)
        self._search._deduplicate_and_merge(metrics)
        if verbose:
            merged = before_dedupe - len(self._search.papers)
            logger.info(
                "Dedupe: %d -> %d papers (%d merged)",
                before_dedupe,
                len(self._results),
                merged,
            )
        # Apply post-fetch date filters.  Connectors that only support
        # year-level date filtering may return papers outside the requested
        # range; _matches_filters enforces precise boundaries.
        if self._since is not None or self._until is not None:
            before_filter = len(self._search.papers)
            self._search.papers = [p for p in self._search.papers if self._matches_filters(p)]
            if verbose:
                logger.info(
                    "Post-fetch filter: %d -> %d papers (%d removed)",
                    before_filter,
                    len(self._search.papers),
                    before_filter - len(self._search.papers),
                )
        # Enrich the filtered papers via per-paper get() lookups.
        # enrichment_databases=None  → enrich with all available databases.
        # enrichment_databases=[]    → skip enrichment entirely.
        if not (
            isinstance(self._enrichment_databases, list) and len(self._enrichment_databases) == 0
        ):
            super()._enrich_papers(
                self._search.papers,
                verbose,
                show_progress=show_progress,
                num_workers=self._num_workers,
            )
        metrics["total_papers"] = len(self._search.papers)
        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics

        if verbose:
            logger.info("=== Results ===")
            logger.info("Total papers: %d", metrics["total_papers"])
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            for searcher in self._searchers:
                count = int(metrics.get(f"total_papers_from_{searcher.name}", 0))
                logger.info("  %s: %d papers", searcher.name, count)
        # Update of search attributes
        self._search.runtime_seconds = self._metrics.get("runtime_in_seconds")
        self._search.processed_at = datetime.now(UTC)
        _root_logger.setLevel(_saved_log_level)
        return self._search

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_searchers(
        self,
        *,
        databases: list[str] | None,
        ieee_api_key: str | None,
        scopus_api_key: str | None,
        pubmed_api_key: str | None,
        openalex_api_key: str | None,
        email: str | None,
        semantic_scholar_api_key: str | None,
        wos_api_key: str | None,
    ) -> tuple[list[SearchConnectorBase], list[str]]:
        """Instantiate the requested searchers.

        Parameters
        ----------
        databases : list[str] | None
            Requested database identifiers.
        ieee_api_key : str | None
            IEEE API key.
        scopus_api_key : str | None
            Scopus API key.
        pubmed_api_key : str | None
            PubMed API key.
        openalex_api_key : str | None
            OpenAlex API key.
        email : str | None
            Polite-pool email.
        semantic_scholar_api_key : str | None
            Semantic Scholar API key.
        wos_api_key : str | None
            Web of Science API key.

        Returns
        -------
        tuple[list[SearchConnectorBase], list[str]]
            A pair of (available searchers, names of skipped searchers).

        Raises
        ------
        InvalidParameterError
            When an unknown database identifier is provided.
        """
        # Per-database constructor credentials.  Databases with no entry
        # (e.g. Arxiv) are constructed with no arguments.  The class for
        # each Database is looked up in the central SEARCH_REGISTRY so
        # that this runner does not need to import every concrete connector.
        _credentials: dict[Database, dict[str, str | None]] = {
            Database.IEEE: {"api_key": ieee_api_key},
            Database.OPENALEX: {"api_key": openalex_api_key, "email": email},
            Database.PUBMED: {"api_key": pubmed_api_key},
            Database.SCOPUS: {"api_key": scopus_api_key},
            Database.SEMANTIC_SCHOLAR: {"api_key": semantic_scholar_api_key},
            Database.WOS: {"api_key": wos_api_key},
        }

        valid_values = {db.value for db in SEARCH_REGISTRY}

        # Treat an explicit empty list as an error – the caller likely
        # intended to pass ``None`` (select all) instead of ``[]``.
        if databases is not None and len(databases) == 0:
            raise InvalidParameterError(
                "databases must not be an empty list. Pass None to select all available databases."
            )

        raw = [db.strip().lower() for db in (databases or [db.value for db in SEARCH_REGISTRY])]
        unknown = [db for db in raw if db not in valid_values]
        if unknown:
            raise InvalidParameterError(
                f"Unknown database(s): {', '.join(unknown)}. "
                f"Accepted values: {', '.join(sorted(valid_values))}"
            )

        searchers: list = []
        skipped: list[str] = []
        for db in raw:
            try:
                searcher = SEARCH_REGISTRY[Database(db)](**_credentials.get(Database(db), {}))
                searchers.append(searcher)
            except MissingApiKeyError:
                skipped.append(Database(db).value)
                logger.warning(
                    "Skipping '%s': a required API key was not provided.",
                    Database(db).value,
                )
        return searchers, skipped

    def _fetch_papers(
        self,
        metrics: dict[str, int | float],
        verbose: bool = False,
        *,
        show_progress: bool = True,
    ) -> tuple[list[str], dict[str, float]]:
        """Fetch papers from all configured searchers.

        Updates *metrics* with per-database paper counts.

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
        tuple[list[str], dict[str, float]]
            A pair of (names of databases that failed during the search,
            per-database wall-clock runtime in seconds).  Databases skipped
            due to unsupported queries are **not** included in failures.
        """

        num_searchers = len(self._searchers)
        num_workers = min(self._num_workers, num_searchers)

        # Create a persistent progress bar for every database upfront, each
        # pinned to a fixed terminal row via ``position``.  This guarantees
        # all bars are visible simultaneously in both serial and parallel
        # modes — workers update their own bar in-place rather than printing
        # new lines or clearing a shared temporary bar.
        db_bars = [
            make_progress_bar(
                desc=f"Searching - {searcher.name}",
                unit="paper",
                disable=not show_progress,
                leave=True,
                position=i,
            )
            for i, searcher in enumerate(self._searchers)
        ]
        bar_by_searcher = dict(zip(self._searchers, db_bars, strict=True))

        def _run_searcher(searcher: SearchConnectorBase) -> tuple[list[Paper], float]:
            """Run a single searcher and update its pre-assigned progress bar.

            Parameters
            ----------
            searcher : SearchConnectorBase
                Connector to execute.

            Returns
            -------
            tuple[list[Paper], float]
                Retrieved papers and wall-clock runtime in seconds.
            """
            pbar = bar_by_searcher[searcher]

            def _cb(current: int, total: int | None) -> None:
                pbar.total = total
                pbar.n = current
                pbar.refresh()

            db_start = perf_counter()
            papers = searcher.search(
                self._query,
                max_papers=self._max_papers_per_database,
                progress_callback=_cb,
                since=self._since,
                until=self._until,
            )
            elapsed = perf_counter() - db_start

            # When the connector exits early (e.g. first request returns an
            # error or zero results) total may still be None, leaving the bar
            # in indeterminate mode.  Force an exit from indeterminate state so
            # the bar looks visually finished rather than frozen.
            if pbar.total is None:
                pbar.total = pbar.n
            # A bar with total == 0 (whether explicitly reported by the API or
            # set above after an early exit) retains the indeterminate
            # '?paper/s' display in tqdm, which looks identical to 'still
            # running'.  Adding a 'done' postfix makes it obvious at a glance
            # that the search completed with no results.
            if pbar.total == 0:
                pbar.set_postfix_str("done")
            pbar.refresh()

            return papers, elapsed

        failed: list[str] = []
        db_runtimes: dict[str, float] = {}
        try:
            for searcher, result, error in execute_tasks(
                self._searchers,
                _run_searcher,
                num_workers=num_workers,
                timeout=None,
                use_progress=False,
            ):
                if error is not None or result is None:
                    metrics[f"total_papers_from_{searcher.name}"] = 0
                    if isinstance(error, UnsupportedQueryError):
                        logger.warning("Skipping '%s': %s", searcher.name, error)
                    else:
                        failed.append(searcher.name)
                        logger.warning("Error fetching from %s: %s", searcher.name, error)
                        logger.debug("Exception details for %s:", searcher.name, exc_info=error)
                else:
                    papers, elapsed = result
                    db_runtimes[searcher.name] = elapsed
                    metrics[f"total_papers_from_{searcher.name}"] = len(papers)
                    self._results.extend(papers)
        finally:
            # Ensure every bar exits indeterminate mode before closing,
            # covering the edge case where _run_searcher itself raised an
            # unhandled exception and never got to finalize its own bar.
            for pbar in db_bars:
                if pbar.total is None:
                    pbar.total = pbar.n
                if pbar.total == 0:
                    # refresh=False: avoid the same positional misalignment
                    # that removing pbar.refresh() above is meant to fix.
                    pbar.set_postfix_str("done", refresh=False)
                pbar.close()

        return failed, db_runtimes

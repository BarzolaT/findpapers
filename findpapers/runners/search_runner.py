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
from findpapers.runners.base_runner import BaseRunner
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.parallel import execute_tasks
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)

_PREPRINT_DOI_PREFIXES: frozenset[str] = frozenset(
    {
        "10.48550/arxiv.",  # arXiv
        "10.1101/",  # bioRxiv / medRxiv
        "10.2139/ssrn.",  # SSRN
        "10.5281/zenodo.",  # Zenodo
        "10.20944/preprints",  # Preprints.org
    }
)


def _is_preprint_doi(doi: str) -> bool:
    """Return ``True`` when *doi* belongs to a preprint server.

    Parameters
    ----------
    doi : str
        DOI string (without ``https://doi.org/`` prefix).

    Returns
    -------
    bool
        ``True`` for known preprint-server DOI prefixes.
    """
    lowered = doi.strip().lower()
    return any(lowered.startswith(prefix) for prefix in _PREPRINT_DOI_PREFIXES)


class SearchRunner(BaseRunner):
    """Public API entry point for running academic paper searches.

    The runner orchestrates the full pipeline:

    1. Parse and validate the query string.
    2. Fetch papers from each configured database searcher.
    3. Deduplicate and merge results using a two-pass strategy: first by
       DOI when available, then a second pass by normalised title+year to
       catch cross-database cases where the same paper carries different DOIs
       (e.g. arXiv preprint DOI vs. publisher DOI).
    4. Filter by ``paper_types`` when specified.

    Parameters
    ----------
    query : str
        Raw query string (e.g. ``"ti[machine learning] AND abs[deep learning]"``).
    databases : list[str] | None
        Database identifiers to query.  When ``None`` all supported databases
        are used.  Supported values: ``"arxiv"``, ``"ieee"``, ``"openalex"``,
        ``"pubmed"``, ``"scopus"``, ``"semantic_scholar"``.
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
    num_workers : int
        Number of parallel workers for running database searchers
        concurrently.  Defaults to ``1``, which runs all searchers
        sequentially.  Values greater than ``1`` enable parallel execution.
    since : dt.date | None
        Only return papers published on or after this date.
    until : dt.date | None
        Only return papers published on or before this date.
    paper_types : list[str] | None
        When set, only papers whose type is in this list are returned.
        Allowed values: ``"article"``, ``"inproceedings"``, ``"inbook"``,
        ``"incollection"``, ``"book"``, ``"phdthesis"``,
        ``"mastersthesis"``, ``"techreport"``, ``"unpublished"``,
        ``"misc"``.  Papers with an unknown type are excluded when this
        filter is active.  ``None`` (default) disables the filter.

    Raises
    ------
    findpapers.exceptions.QueryValidationError
        If the query string fails validation.

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
        num_workers: int = 1,
        since: dt.date | None = None,
        until: dt.date | None = None,
        paper_types: list[str] | None = None,
    ) -> None:
        """Initialise search configuration without executing it."""
        self._results: list[Paper] = []
        self._metrics: dict[str, int | float] = {}
        self._search: SearchResult | None = None

        super().__init__(since=since, until=until, paper_types=paper_types)

        self._query_string = query
        self._max_papers_per_database = max_papers_per_database
        self._num_workers = num_workers

        # Parse and validate the query upfront so errors surface early.
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

        before_dedupe = len(self._results)
        self._deduplicate_and_merge(metrics)
        if verbose:
            merged = before_dedupe - len(self._results)
            logger.info(
                "Dedupe: %d -> %d papers (%d merged)",
                before_dedupe,
                len(self._results),
                merged,
            )

        # Apply post-fetch filters (paper type + exact date range).  Connectors
        # that only support year-level date filtering may return papers outside
        # the requested range; _matches_filters enforces precise boundaries.
        if self._paper_types is not None or self._since is not None or self._until is not None:
            before_filter = len(self._results)
            self._results = [p for p in self._results if self._matches_filters(p)]
            if verbose:
                logger.info(
                    "Post-fetch filter: %d -> %d papers (%d removed)",
                    before_filter,
                    len(self._results),
                    before_filter - len(self._results),
                )

        metrics["total_papers"] = len(self._results)
        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics

        if verbose:
            logger.info("=== Results ===")
            logger.info("Total papers: %d", metrics["total_papers"])
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            for searcher in self._searchers:
                count = int(metrics.get(f"total_papers_from_{searcher.name}", 0))
                logger.info("  %s: %d papers", searcher.name, count)

        self._search = SearchResult(
            query=self._query_string,
            max_papers_per_database=self._max_papers_per_database,
            processed_at=datetime.now(UTC),
            databases=[s.name for s in self._searchers],
            papers=list(self._results),
            runtime_seconds=self._metrics.get("runtime_in_seconds"),
            runtime_seconds_per_database=db_runtimes or None,
            since=self._since,
            until=self._until,
            failed_databases=failed_databases or None,
        )
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

        def _run_searcher(
            searcher: SearchConnectorBase,
            *,
            parallel: bool = False,
        ) -> tuple[list[Paper], float]:
            """Run a single searcher with a per-database tqdm bar.

            Parameters
            ----------
            searcher : SearchConnectorBase
                Connector to execute.
            parallel : bool
                When ``True``, the searcher is being called from a thread
                pool.  The inner progress bar is disabled to avoid
                interleaved output across threads.

            Returns
            -------
            tuple[list[Paper], float]
                Retrieved papers and wall-clock runtime in seconds.
            """
            inner_show = show_progress and not parallel
            with make_progress_bar(
                desc=f"  {searcher.name}",
                unit="paper",
                disable=not inner_show,
                leave=False,
            ) as pbar:

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
                return papers, elapsed

        num_searchers = len(self._searchers)
        num_workers = min(self._num_workers, num_searchers)
        parallel = num_workers > 1

        # Wrap searchers so _run_searcher receives the parallel flag.
        def _run_searcher_bound(searcher: SearchConnectorBase) -> tuple[list[Paper], float]:
            return _run_searcher(searcher, parallel=parallel)

        failed: list[str] = []
        db_runtimes: dict[str, float] = {}
        db_count = 0
        with make_progress_bar(
            desc=f"Database 1/{num_searchers}",
            total=num_searchers,
            unit="db",
            leave=True,
            disable=not show_progress,
        ) as outer_pbar:
            for searcher, result, error in execute_tasks(
                self._searchers,
                _run_searcher_bound,
                num_workers=num_workers,
                timeout=None,
                use_progress=False,
            ):
                db_count += 1
                outer_pbar.set_description(f"Database {db_count}/{num_searchers}")
                if error is not None or result is None:
                    metrics[f"total_papers_from_{searcher.name}"] = 0
                    if isinstance(error, UnsupportedQueryError):
                        logger.warning("Skipping '%s': %s", searcher.name, error)
                    else:
                        failed.append(searcher.name)
                        if verbose:
                            logger.warning("Error fetching from %s: %s", searcher.name, error)
                else:
                    papers, elapsed = result
                    db_runtimes[searcher.name] = elapsed
                    metrics[f"total_papers_from_{searcher.name}"] = len(papers)
                    self._results.extend(papers)
                outer_pbar.update(1)

        return failed, db_runtimes

    def _deduplicate_and_merge(self, metrics: dict[str, int | float]) -> None:
        """Collapse duplicate papers in two passes.

        **Pass 1** groups papers by their primary key (DOI when available,
        otherwise a normalised ``title|year`` string).  This resolves exact
        duplicates found within the same database or between databases that
        share the same DOI.

        **Pass 2** groups the results of pass 1 by normalised title and
        merges entries whose publication years are *compatible* — i.e. they
        share the same year, at least one has no year (incomplete metadata),
        or at least one entry carries a preprint DOI and their years differ by
        at most one (to handle both the case of the same preprint deposited to
        two servers across the Dec/Jan calendar boundary and the common
        preprint-to-published transition, e.g. Zenodo 2026 + book chapter
        2025).  Papers with the same title and *different known years* where
        neither is from a preprint server are intentionally kept separate.

        This correctly handles the common cross-database case where the same
        work is indexed with different DOIs (e.g. an arXiv preprint DOI vs a
        publisher DOI) and one of the database records lacks a publication
        date.

        When two papers are deemed duplicates their data is merged using
        :meth:`~findpapers.core.paper.Paper.merge` (most-complete strategy).

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict (currently unused; reserved for future statistics).

        Returns
        -------
        None
        """
        # Pass 1: primary key dedup (DOI > title|year > title).
        pass1: dict[str, Paper] = {}
        for paper in self._results:
            key = self._dedupe_key(paper)
            if key in pass1:
                pass1[key].merge(paper)
            else:
                pass1[key] = paper

        # Pass 2: title-based dedup that handles missing year metadata.
        # Group survivors from pass 1 by normalised title, then within each
        # title group greedily merge papers whose years are compatible.
        by_title: dict[str, list[Paper]] = {}
        untitled: list[Paper] = []
        for paper in pass1.values():
            norm_title = paper.title.strip().lower() if paper.title else ""
            if norm_title:
                by_title.setdefault(norm_title, []).append(paper)
            else:
                untitled.append(paper)

        result: list[Paper] = list(untitled)
        for candidates in by_title.values():
            # Greedily merge into the first compatible representative.
            groups: list[Paper] = []
            for paper in candidates:
                paper_year = getattr(paper.publication_date, "year", None)
                merged_into: Paper | None = None
                for representative in groups:
                    rep_year = getattr(representative.publication_date, "year", None)
                    if _are_years_compatible(rep_year, paper_year, representative.doi, paper.doi):
                        merged_into = representative
                        break
                if merged_into is not None:
                    merged_into.merge(paper)
                else:
                    groups.append(paper)
            result.extend(groups)

        self._results = result

    def _dedupe_key(self, paper: Paper) -> str:
        """Build a stable primary deduplication key for a paper.

        Uses the DOI when available; otherwise falls back to a normalised
        ``title|year`` combination.

        Parameters
        ----------
        paper : Paper
            Paper to key.

        Returns
        -------
        str
            Dedupe key string.
        """
        if paper.doi:
            return f"doi:{str(paper.doi).strip().lower()}"
        return self._title_year_key(paper)

    def _title_year_key(self, paper: Paper) -> str:
        """Build a normalised ``title|year`` deduplication key for a paper.

        Used as the pass-1 fallback dedup key when no DOI is available.
        Two records without a DOI but with the same title and the same year
        are considered identical and are merged in pass 1.

        Parameters
        ----------
        paper : Paper
            Paper to key.

        Returns
        -------
        str
            Title/year key string.
        """
        title = paper.title
        year = getattr(paper.publication_date, "year", None)
        if title and year:
            return f"title:{str(title).strip().lower()}|year:{year}"
        if title:
            return f"title:{str(title).strip().lower()}"
        return f"object:{id(paper)}"


def _are_years_compatible(
    year_a: int | None,
    year_b: int | None,
    doi_a: str | None,
    doi_b: str | None,
) -> bool:
    """Return whether two publication years are compatible for merging.

    Two papers are considered year-compatible when:

    * Either year is unknown (``None``), or
    * Both years are identical, or
    * Their years differ by exactly 1 **and** at least one DOI belongs to a
      preprint server (covers preprint-to-published transitions across the
      Dec/Jan boundary).

    Parameters
    ----------
    year_a : int | None
        Publication year of the first paper.
    year_b : int | None
        Publication year of the second paper.
    doi_a : str | None
        DOI of the first paper.
    doi_b : str | None
        DOI of the second paper.

    Returns
    -------
    bool
        ``True`` when the years are compatible for merging.
    """
    if year_a is None or year_b is None or year_a == year_b:
        return True

    # Adjacent-year preprint check.
    raw_doi_a = doi_a or ""
    raw_doi_b = doi_b or ""
    return (
        abs(year_a - year_b) == 1
        and bool(raw_doi_a)
        and bool(raw_doi_b)
        and (_is_preprint_doi(raw_doi_a) or _is_preprint_doi(raw_doi_b))
    )

"""SearchRunner: the main entry point for performing academic paper searches."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter

from findpapers.core.paper import Paper, PaperType
from findpapers.core.search import Database, Search
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.query.parser import QueryParser
from findpapers.query.validator import QueryValidator
from findpapers.searchers.arxiv import ArxivSearcher
from findpapers.searchers.base import SearcherBase
from findpapers.searchers.ieee import IEEESearcher
from findpapers.searchers.openalex import OpenAlexSearcher
from findpapers.searchers.pubmed import PubmedSearcher
from findpapers.searchers.scopus import ScopusSearcher
from findpapers.searchers.semantic_scholar import SemanticScholarSearcher
from findpapers.utils.parallel import execute_tasks
from findpapers.utils.predatory import is_predatory_publication
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)


class SearchRunner:
    """Public API entry point for running academic paper searches.

    The runner orchestrates the full pipeline:

    1. Parse and validate the query string.
    2. Fetch papers from each configured database searcher.
    3. Filter by publication type (when specified).
    4. Deduplicate and merge results using DOI / title+year keys.
    5. Flag papers from potentially predatory publications.

    Parameters
    ----------
    query : str
        Raw query string (e.g. ``"ti[machine learning] AND abs[deep learning]"``).
    databases : list[str] | None
        Database identifiers to query.  When ``None`` all supported databases
        are used.  Supported values: ``"arxiv"``, ``"ieee"``, ``"openalex"``,
        ``"pubmed"``, ``"scopus"``, ``"semantic_scholar"``.
    paper_types : list[str] | None
        Restrict results to papers of these BibTeX-aligned types.  Accepted
        values: ``"article"``, ``"inbook"``, ``"incollection"``,
        ``"inproceedings"``, ``"manual"``, ``"mastersthesis"``,
        ``"phdthesis"``, ``"techreport"``, ``"unpublished"``.
        ``None`` means no type filtering.  Papers with an undetermined type are
        always discarded regardless of this parameter.
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
    openalex_email : str | None
        Contact email for OpenAlex polite pool (recommended).
    semantic_scholar_api_key : str | None
        Semantic Scholar API key (increases rate limit).
    num_workers : int
        Number of parallel workers for running database searchers
        concurrently.  Defaults to ``1``, which runs all searchers
        sequentially.  Values greater than ``1`` enable parallel execution.

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
    >>> runner.run()
    >>> papers = runner.get_results()
    """

    def __init__(
        self,
        query: str,
        databases: list[str] | None = None,
        paper_types: list[str] | None = None,
        max_papers_per_database: int | None = None,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        openalex_email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        num_workers: int = 1,
    ) -> None:
        """Initialise search configuration without executing it."""
        self._executed = False
        self._results: list[Paper] = []
        self._metrics: dict[str, int | float] = {}
        self._search: Search | None = None

        self._query_string = query
        self._paper_types = self._validate_paper_types(paper_types)
        self._max_papers_per_database = max_papers_per_database
        self._num_workers = num_workers

        # Parse and validate the query upfront so errors surface early.
        validator = QueryValidator()
        validator.validate(query)
        parser = QueryParser()
        self._query = parser.parse(query)

        self._searchers = self._build_searchers(
            databases=databases,
            ieee_api_key=ieee_api_key,
            scopus_api_key=scopus_api_key,
            pubmed_api_key=pubmed_api_key,
            openalex_api_key=openalex_api_key,
            openalex_email=openalex_email,
            semantic_scholar_api_key=semantic_scholar_api_key,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False) -> Search:
        """Execute the configured pipeline and return the results.

        Can be called multiple times; each call resets previous results.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.

        Returns
        -------
        Search
            Search result object containing papers and metadata.
        """
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            # Suppress verbose output from third-party HTTP libraries so that
            # only findpapers' own loggers emit debug messages.
            for _noisy in ("urllib3", "requests", "httpx", "charset_normalizer"):
                logging.getLogger(_noisy).setLevel(logging.WARNING)
            logger.info("=== SearchRunner Configuration ===")
            logger.info("Databases: %s", [s.name for s in self._searchers])
            logger.info("Paper types: %s", self._paper_types or "all")
            logger.info("Num workers: %d", self._num_workers)
            logger.info("Query: %s", self._query_string)
            logger.info("Max papers per database: %s", self._max_papers_per_database or "none")
            logger.info("==================================")

        start = perf_counter()
        self._results = []
        metrics: dict[str, int | float] = {
            "total_papers": 0,
            "runtime_in_seconds": 0.0,
            "total_papers_from_predatory_publication": 0,
        }

        self._fetch_papers(metrics, verbose)

        before_filter = len(self._results)
        self._filter_by_paper_types(metrics)
        if verbose:
            removed = before_filter - len(self._results)
            logger.info(
                "Filter: %d -> %d papers (%d removed)",
                before_filter,
                len(self._results),
                removed,
            )

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

        self._flag_predatory(metrics)
        if verbose:
            logger.info(
                "Predatory flagging: %d papers flagged",
                int(metrics["total_papers_from_predatory_publication"]),
            )

        metrics["total_papers"] = len(self._results)
        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics
        self._executed = True

        if verbose:
            logger.info("=== Results ===")
            logger.info("Total papers: %d", metrics["total_papers"])
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            for searcher in self._searchers:
                count = int(metrics.get(f"total_papers_from_{searcher.name}", 0))
                logger.info("  %s: %d papers", searcher.name, count)

        self._search = Search(
            query=self._query_string,
            max_papers_per_database=self._max_papers_per_database,
            processed_at=datetime.now(timezone.utc),
            databases=[s.name for s in self._searchers],
            paper_types=self._paper_types,
            papers=list(self._results),
            runtime_seconds=self._metrics.get("runtime_in_seconds"),
        )
        return self._search

    def get_results(self) -> list[Paper]:
        """Return a deep copy of the collected papers.

        Returns
        -------
        list[Paper]
            Collected and processed papers.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        return deepcopy(self._results)

    def get_metrics(self) -> dict[str, int | float]:
        """Return a snapshot of numeric performance metrics.

        Returns
        -------
        dict[str, int | float]
            Metrics dictionary with at least ``total_papers``,
            ``runtime_in_seconds``, and
            ``total_papers_from_predatory_publication``.

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

    @staticmethod
    def _validate_paper_types(
        paper_types: list[str] | None,
    ) -> list[str] | None:
        """Validate that each entry in *paper_types* is a known :class:`PaperType`.

        Parameters
        ----------
        paper_types : list[str] | None
            User-provided list of paper type strings.

        Returns
        -------
        list[str] | None
            The same list if all values are valid, or ``None`` when the input
            is ``None``.

        Raises
        ------
        ValueError
            When any value is not a recognised :class:`PaperType` member.
        """
        if paper_types is None:
            return None
        valid_values = {pt.value for pt in PaperType}
        invalid = [pt for pt in paper_types if pt.strip().lower() not in valid_values]
        if invalid:
            raise ValueError(
                f"Unknown paper type(s): {', '.join(invalid)}. "
                f"Accepted values: {', '.join(sorted(valid_values))}"
            )
        return [pt.strip().lower() for pt in paper_types]

    def _ensure_executed(self) -> None:
        """Raise if the runner has not been executed yet.

        Raises
        ------
        SearchRunnerNotExecutedError
            When :meth:`run` has not been called.
        """
        if not self._executed:
            raise SearchRunnerNotExecutedError("SearchRunner has not been executed yet.")

    def _build_searchers(
        self,
        *,
        databases: list[str] | None,
        ieee_api_key: str | None,
        scopus_api_key: str | None,
        pubmed_api_key: str | None,
        openalex_api_key: str | None,
        openalex_email: str | None,
        semantic_scholar_api_key: str | None,
    ) -> list[SearcherBase]:
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
        openalex_email : str | None
            OpenAlex polite-pool email.
        semantic_scholar_api_key : str | None
            Semantic Scholar API key.

        Returns
        -------
        list[SearcherBase]
            Instantiated searchers in the requested order.

        Raises
        ------
        ValueError
            When an unknown database identifier is provided.
        """
        all_searchers: dict[Database, SearcherBase] = {
            Database.ARXIV: ArxivSearcher(),
            Database.IEEE: IEEESearcher(api_key=ieee_api_key),
            Database.OPENALEX: OpenAlexSearcher(api_key=openalex_api_key, email=openalex_email),
            Database.PUBMED: PubmedSearcher(api_key=pubmed_api_key),
            Database.SCOPUS: ScopusSearcher(api_key=scopus_api_key),
            Database.SEMANTIC_SCHOLAR: SemanticScholarSearcher(api_key=semantic_scholar_api_key),
        }

        valid_values = {db.value for db in Database}
        raw = [db.strip().lower() for db in (databases or [db.value for db in Database])]
        unknown = [db for db in raw if db not in valid_values]
        if unknown:
            raise ValueError(
                f"Unknown database(s): {', '.join(unknown)}. "
                f"Accepted values: {', '.join(sorted(valid_values))}"
            )

        searchers = [all_searchers[Database(db)] for db in raw]
        available = []
        for searcher in searchers:
            if searcher.is_available:
                available.append(searcher)
            else:
                logger.warning(
                    "Skipping '%s': a required API key was not provided.",
                    searcher.name,
                )
        return available

    def _fetch_papers(self, metrics: dict[str, int | float], verbose: bool = False) -> None:
        """Fetch papers from all configured searchers.

        Updates *metrics* with per-database paper counts.

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

        def _run_searcher(searcher: SearcherBase) -> list[Paper]:
            """Run a single searcher with a per-database tqdm bar.

            Parameters
            ----------
            searcher : SearcherBase
                Searcher to execute.

            Returns
            -------
            list[Paper]
                Retrieved papers.
            """
            with make_progress_bar(desc=searcher.name, unit="paper") as pbar:

                def _cb(current: int, total: int | None) -> None:
                    pbar.total = total
                    pbar.n = current
                    pbar.refresh()

                return searcher.search(
                    self._query,
                    max_papers=self._max_papers_per_database,
                    progress_callback=_cb,
                )

        num_searchers = len(self._searchers)
        num_workers = min(self._num_workers, num_searchers)

        for searcher, result, error in execute_tasks(
            self._searchers,
            _run_searcher,
            num_workers=num_workers,
            timeout=None,
            use_progress=False,
        ):
            if error is not None or result is None:
                metrics[f"total_papers_from_{searcher.name}"] = 0
                if verbose:
                    logger.warning("Error fetching from %s: %s", searcher.name, error)
                continue
            metrics[f"total_papers_from_{searcher.name}"] = len(result)
            self._results.extend(result)

    def _filter_by_paper_types(self, metrics: dict[str, int | float]) -> None:
        """Discard papers without a recognisable type and optionally restrict
        to the allowed type set.

        Papers whose :attr:`~findpapers.core.paper.Paper.paper_type` is
        ``None`` are always removed because they could not be classified.  When
        ``paper_types`` was supplied at construction time, only papers whose
        type matches one of those values are kept.

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict (currently unused; reserved for future statistics).

        Returns
        -------
        None
        """
        # Always discard papers whose type could not be determined.
        self._results = [p for p in self._results if p.paper_type is not None]

        # If the caller requested specific types, apply that secondary filter.
        if self._paper_types:
            allowed = {pt.strip().lower() for pt in self._paper_types}
            self._results = [
                p
                for p in self._results
                if p.paper_type is not None and p.paper_type.value in allowed
            ]

    def _deduplicate_and_merge(self, metrics: dict[str, int | float]) -> None:
        """Collapse duplicate papers using DOI or title+year as the key.

        When two papers share the same key, their data is merged using
        :meth:`~findpapers.core.paper.Paper.merge` (most-complete strategy).

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict (currently unused; reserved for future statistics).

        Returns
        -------
        None
        """
        merged: dict[str, Paper] = {}
        for paper in self._results:
            key = self._dedupe_key(paper)
            if key in merged:
                merged[key].merge(paper)
            else:
                merged[key] = paper
        self._results = list(merged.values())

    def _flag_predatory(self, metrics: dict[str, int | float]) -> None:
        """Mark papers from potentially predatory publications.

        Parameters
        ----------
        metrics : dict[str, int | float]
            Updated with ``total_papers_from_predatory_publication``.

        Returns
        -------
        None
        """
        flagged = 0
        for paper in self._results:
            if is_predatory_publication(paper.publication):
                if paper.publication is not None:
                    paper.publication.is_potentially_predatory = True
                flagged += 1
        metrics["total_papers_from_predatory_publication"] = flagged

    def _dedupe_key(self, paper: Paper) -> str:
        """Build a stable deduplication key for a paper.

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
        title = paper.title
        year = getattr(paper.publication_date, "year", None)
        if title and year:
            return f"title:{str(title).strip().lower()}|year:{year}"
        if title:
            return f"title:{str(title).strip().lower()}"
        return f"object:{id(paper)}"

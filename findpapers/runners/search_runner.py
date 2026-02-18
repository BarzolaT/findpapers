"""SearchRunner: the main entry point for performing academic paper searches."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from time import perf_counter

from findpapers.core.paper import Paper
from findpapers.core.search import Search
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.query.parser import QueryParser
from findpapers.query.validator import QueryValidator
from findpapers.searchers.arxiv import ArxivSearcher
from findpapers.searchers.base import SearcherBase
from findpapers.searchers.biorxiv import BiorxivSearcher
from findpapers.searchers.ieee import IEEESearcher
from findpapers.searchers.medrxiv import MedrxivSearcher
from findpapers.searchers.openalex import OpenAlexSearcher
from findpapers.searchers.pubmed import PubmedSearcher
from findpapers.searchers.scopus import ScopusSearcher
from findpapers.searchers.semantic_scholar import SemanticScholarSearcher
from findpapers.utils.parallel import execute_tasks
from findpapers.utils.predatory import is_predatory_publication
from findpapers.utils.progress import make_progress_bar

logger = logging.getLogger(__name__)

# Canonical database identifiers.
_ALL_DATABASES = [
    "arxiv",
    "biorxiv",
    "ieee",
    "medrxiv",
    "openalex",
    "pubmed",
    "scopus",
    "semantic_scholar",
]


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
        are used.  Supported values: ``"arxiv"``, ``"biorxiv"``, ``"ieee"``,
        ``"medrxiv"``, ``"openalex"``, ``"pubmed"``, ``"scopus"``,
        ``"semantic_scholar"``.
    publication_types : list[str] | None
        Restrict results to these publication categories (e.g.
        ``["journal-article", "conference-paper"]``).  ``None`` means no
        filtering.
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
    max_workers : int | None
        Maximum number of parallel workers for running database searchers
        concurrently.  ``None`` runs all searchers sequentially.

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
        publication_types: list[str] | None = None,
        max_papers_per_database: int | None = None,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        openalex_email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        max_workers: int | None = None,
    ) -> None:
        """Initialise search configuration without executing it."""
        self._executed = False
        self._results: list[Paper] = []
        self._metrics: dict[str, int | float] = {}
        self._search: Search | None = None

        self._query_string = query
        self._publication_types = publication_types
        self._max_papers_per_database = max_papers_per_database
        self._max_workers = max_workers

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
            logging.getLogger().setLevel(logging.INFO)
            logger.info("=== SearchRunner Configuration ===")
            logger.info("Databases: %s", [s.name for s in self._searchers])
            logger.info("Publication types: %s", self._publication_types or "all")
            logger.info("Max workers: %s", self._max_workers or "sequential")
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
        self._filter_by_publication_types(metrics)
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
            publication_types=self._publication_types,
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

    def to_json(self, path: str) -> None:
        """Export results to a JSON file.

        Parameters
        ----------
        path : str
            Output file path.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        from findpapers.utils.export import export_to_json

        assert self._search is not None  # noqa: S101  (post-run guarantee)
        export_to_json(self._search, path)

    def to_csv(self, path: str) -> None:
        """Export results to a CSV file.

        Parameters
        ----------
        path : str
            Output file path.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        from findpapers.utils.export import export_to_csv

        assert self._search is not None  # noqa: S101
        export_to_csv(self._search, path)

    def to_bibtex(self, path: str) -> None:
        """Export results to a BibTeX file.

        Parameters
        ----------
        path : str
            Output file path.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        from findpapers.utils.export import export_to_bibtex

        assert self._search is not None  # noqa: S101
        export_to_bibtex(self._search, path)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
        all_searchers: dict[str, SearcherBase] = {
            "arxiv": ArxivSearcher(),
            "biorxiv": BiorxivSearcher(),
            "ieee": IEEESearcher(api_key=ieee_api_key),
            "medrxiv": MedrxivSearcher(),
            "openalex": OpenAlexSearcher(api_key=openalex_api_key, email=openalex_email),
            "pubmed": PubmedSearcher(api_key=pubmed_api_key),
            "scopus": ScopusSearcher(api_key=scopus_api_key),
            "semantic_scholar": SemanticScholarSearcher(api_key=semantic_scholar_api_key),
        }

        requested = [db.strip().lower() for db in (databases or _ALL_DATABASES)]
        unknown = [db for db in requested if db not in all_searchers]
        if unknown:
            raise ValueError(f"Unknown database(s): {', '.join(unknown)}")

        return [all_searchers[db] for db in requested]

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

        max_workers = self._max_workers if isinstance(self._max_workers, int) else None

        for searcher, result, error in execute_tasks(
            self._searchers,
            _run_searcher,
            max_workers=max_workers,
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

    def _filter_by_publication_types(self, metrics: dict[str, int | float]) -> None:
        """Remove papers whose publication type is not in the allowed list.

        Parameters
        ----------
        metrics : dict[str, int | float]
            Metrics dict (currently unused; reserved for future statistics).

        Returns
        -------
        None
        """
        if not self._publication_types:
            return
        allowed = {pt.strip().lower() for pt in self._publication_types}
        self._results = [
            p
            for p in self._results
            if p.publication is not None
            and p.publication.category is not None
            and p.publication.category.value.strip().lower() in allowed
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

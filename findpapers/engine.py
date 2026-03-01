"""Engine: centralised entry point for all findpapers operations.

An :class:`Engine` instance holds shared configuration (API keys, proxy
settings, timeouts) so that callers configure once and invoke multiple
operations without repeating those details.

Example
-------
>>> from findpapers import Engine
>>> engine = Engine(
...     ieee_api_key="...",
...     scopus_api_key="...",
...     proxy="http://proxy:8080",
... )
>>> result = engine.search("[machine learning]", databases=["arxiv", "ieee"])
>>> engine.enrich(result.papers, num_workers=4)
>>> engine.download(result.papers, "./pdfs")
"""

from __future__ import annotations

import os

from findpapers.core.paper import Paper
from findpapers.core.search_result import SearchResult
from findpapers.runners.doi_lookup_runner import DOILookupRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner


class Engine:
    """Centralised facade for findpapers operations.

    Holds shared configuration — API keys, proxy, and SSL settings — that
    would otherwise need to be repeated in every call.  Per-call parameters
    such as *num_workers*, *timeout*, and *verbose* are passed directly to
    each method.

    All parameters fall back to the corresponding ``FINDPAPERS_*``
    environment variable when not supplied explicitly.

    Parameters
    ----------
    ieee_api_key : str | None
        IEEE Xplore API key.  Required to query the ``"ieee"`` database.
        Falls back to ``FINDPAPERS_IEEE_API_TOKEN``.
    scopus_api_key : str | None
        Elsevier / Scopus API key.  Required to query ``"scopus"``.
        Falls back to ``FINDPAPERS_SCOPUS_API_TOKEN``.
    pubmed_api_key : str | None
        NCBI PubMed API key.  Optional — increases the rate limit.
        Falls back to ``FINDPAPERS_PUBMED_API_TOKEN``.
    openalex_api_key : str | None
        OpenAlex API key.  Optional.
        Falls back to ``FINDPAPERS_OPENALEX_API_TOKEN``.
    email : str | None
        Contact email used for polite-pool access on APIs that support it
        (currently OpenAlex and CrossRef).  Highly recommended to avoid
        being rate-limited.
        Falls back to ``FINDPAPERS_EMAIL``.
    semantic_scholar_api_key : str | None
        Semantic Scholar API key.  Optional — increases the rate limit.
        Falls back to ``FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN``.
    proxy : str | None
        Proxy URL (e.g. ``"http://proxy:8080"``).
        Falls back to ``FINDPAPERS_PROXY``.
    ssl_verify : bool
        Whether to verify SSL certificates.  Set to ``False`` when using
        institutional proxies that perform SSL inspection.
        Defaults to ``True``.  Falls back to ``FINDPAPERS_SSL_VERIFY``
        (accepted values: ``"0"``, ``"false"``, ``"no"`` → ``False``).

    Examples
    --------
    >>> from findpapers import Engine
    >>> engine = Engine(ieee_api_key="my-key", proxy="http://proxy:8080")
    >>> result = engine.search("[deep learning]", databases=["arxiv", "ieee"])
    >>> engine.download(result.papers, "./pdfs", num_workers=4)
    """

    def __init__(
        self,
        *,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        email: str | None = None,
        semantic_scholar_api_key: str | None = None,
        proxy: str | None = None,
        ssl_verify: bool = True,
    ) -> None:
        """Initialise engine with shared configuration.

        Values not supplied explicitly are resolved from environment
        variables (see class docstring for the mapping).
        """
        self._ieee_api_key = ieee_api_key or os.environ.get("FINDPAPERS_IEEE_API_TOKEN") or None
        self._scopus_api_key = (
            scopus_api_key or os.environ.get("FINDPAPERS_SCOPUS_API_TOKEN") or None
        )
        self._pubmed_api_key = (
            pubmed_api_key or os.environ.get("FINDPAPERS_PUBMED_API_TOKEN") or None
        )
        self._openalex_api_key = (
            openalex_api_key or os.environ.get("FINDPAPERS_OPENALEX_API_TOKEN") or None
        )
        self._email = email or os.environ.get("FINDPAPERS_EMAIL") or None
        self._semantic_scholar_api_key = (
            semantic_scholar_api_key
            or os.environ.get("FINDPAPERS_SEMANTIC_SCHOLAR_API_TOKEN")
            or None
        )
        self._proxy = proxy or os.environ.get("FINDPAPERS_PROXY") or None

        # ssl_verify: only fall back to env when caller omits the argument
        # (i.e. uses the default True).  Env values "0", "false", "no"
        # are treated as False.
        if ssl_verify is True and os.environ.get("FINDPAPERS_SSL_VERIFY"):
            self._ssl_verify = os.environ["FINDPAPERS_SSL_VERIFY"].lower() not in (
                "0",
                "false",
                "no",
            )
        else:
            self._ssl_verify = ssl_verify

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        databases: list[str] | None = None,
        max_papers_per_database: int | None = None,
        num_workers: int = 1,
        verbose: bool = False,
    ) -> SearchResult:
        """Search for academic papers across multiple databases.

        Queries one or more academic databases and returns a
        :class:`~findpapers.core.search_result.SearchResult` object with the
        collected papers already deduplicated and merged.

        Query syntax
        ~~~~~~~~~~~~
        Wrap each search term in square brackets and combine them with
        ``AND``, ``OR``, or ``NOT`` operators.  Optionally prefix a term or
        group with a **filter code** to restrict where it is matched:

        * ``ti`` — title
        * ``abs`` — abstract
        * ``key`` — keywords
        * ``au`` — author
        * ``src`` — source (journal / conference)
        * ``aff`` — affiliation
        * ``tiabs`` — title + abstract (default when no filter is given)
        * ``tiabskey`` — title + abstract + keywords

        Example queries::

            "[machine learning]"                              # simple
            "ti[deep learning] AND abs[transformer]"           # with filters
            "[covid-19] AND ([treatment] OR [vaccine])"        # grouping

        Supported databases
        ~~~~~~~~~~~~~~~~~~~
        ``"arxiv"``, ``"ieee"`` (requires API key), ``"openalex"``,
        ``"pubmed"``, ``"scopus"`` (requires API key),
        ``"semantic_scholar"``.

        When *databases* is ``None`` every database that does **not** require
        a missing API key is queried automatically.

        Parameters
        ----------
        query : str
            Query string following the syntax described above.
        databases : list[str] | None
            Database identifiers to query.  ``None`` (default) selects all
            databases whose required API keys are available.
        max_papers_per_database : int | None
            Cap on the number of papers retrieved from each database.
            ``None`` means no limit.
        num_workers : int
            Number of parallel workers used to query databases concurrently.
            Defaults to ``1`` (sequential).
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.
            Defaults to ``False``.

        Returns
        -------
        SearchResult
            A :class:`~findpapers.core.search_result.SearchResult` object
            whose ``papers`` attribute contains the collected
            :class:`~findpapers.core.paper.Paper` instances.  The result can
            be exported directly via ``result.to_json()``,
            ``result.to_csv()``, or ``result.to_bibtex()``.

        Raises
        ------
        findpapers.exceptions.QueryValidationError
            If *query* has syntax errors (unbalanced brackets, invalid filter
            codes, etc.).
        ValueError
            If an unknown database name is passed in *databases*.

        See Also
        --------
        findpapers.runners.search_runner.SearchRunner :
            Lower-level class for when you need access to per-run metrics or
            want to separate configuration from execution.

        Examples
        --------
        Basic search across all available databases:

        >>> from findpapers import Engine
        >>> engine = Engine()
        >>> result = engine.search("[machine learning]")
        >>> print(f"{len(result.papers)} papers found")
        127 papers found

        Targeted search with filters and database selection:

        >>> engine = Engine(ieee_api_key="my-key")
        >>> result = engine.search(
        ...     "ti[transformer] AND abs[attention mechanism]",
        ...     databases=["arxiv", "ieee"],
        ...     max_papers_per_database=50,
        ... )

        Export results to a file:

        >>> result.to_json("my_search.json")
        >>> result.to_csv("my_search.csv")
        """
        runner = SearchRunner(
            query=query,
            databases=databases,
            max_papers_per_database=max_papers_per_database,
            ieee_api_key=self._ieee_api_key,
            scopus_api_key=self._scopus_api_key,
            pubmed_api_key=self._pubmed_api_key,
            openalex_api_key=self._openalex_api_key,
            email=self._email,
            semantic_scholar_api_key=self._semantic_scholar_api_key,
            num_workers=num_workers,
        )
        return runner.run(verbose=verbose)

    def download(
        self,
        papers: list[Paper],
        output_directory: str,
        *,
        num_workers: int = 1,
        timeout: float | None = 10.0,
        verbose: bool = False,
    ) -> dict[str, int | float]:
        """Download PDFs for a list of papers.

        For each paper, all known URLs are tried and HTML landing pages are
        followed to resolve the actual PDF link.  Downloaded files are saved
        to *output_directory* with a ``year-title.pdf`` naming scheme.  When
        a download fails the paper is logged to ``download_errors.txt`` inside
        *output_directory*.

        Parameters
        ----------
        papers : list[Paper]
            Papers whose PDFs should be downloaded — typically obtained from
            ``engine.search(...).papers``.
        output_directory : str
            Directory where PDF files and the error log will be written.
            Created automatically if it does not exist.
        num_workers : int
            Number of parallel download workers.  Defaults to ``1``
            (sequential).  Increase to speed up bulk downloads.
        timeout : float | None
            Per-request HTTP timeout in seconds.  ``None`` disables the
            timeout.  Defaults to ``10.0``.
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.
            Defaults to ``False``.

        Returns
        -------
        dict[str, int | float]
            Metrics dictionary with at least the following keys:

            * ``total_papers`` — number of papers attempted.
            * ``downloaded_papers`` — number of successfully downloaded PDFs.
            * ``runtime_in_seconds`` — wall-clock time of the download
              process.

        See Also
        --------
        findpapers.runners.download_runner.DownloadRunner :
            Lower-level class for when you need finer control over the
            download pipeline.

        Examples
        --------
        >>> from findpapers import Engine
        >>> engine = Engine(proxy="http://proxy:8080")
        >>> result = engine.search("[deep learning]", databases=["arxiv"])
        >>> metrics = engine.download(result.papers, "./pdfs")
        >>> print(f"{metrics['downloaded_papers']}/{metrics['total_papers']} downloaded")
        8/10 downloaded
        """
        runner = DownloadRunner(
            papers=papers,
            output_directory=output_directory,
            num_workers=num_workers,
            timeout=timeout,
            proxy=self._proxy,
            ssl_verify=self._ssl_verify,
        )
        runner.run(verbose=verbose)
        return runner.get_metrics()

    def enrich(
        self,
        papers: list[Paper],
        *,
        num_workers: int = 1,
        timeout: float | None = 10.0,
        verbose: bool = False,
    ) -> dict[str, int | float]:
        """Enrich papers with additional metadata from web sources.

        For each paper, metadata is fetched from the CrossRef API (when a DOI
        is available) and by scraping the paper's known URLs.  Found data —
        such as abstracts, keywords, PDF links, citation counts, and source
        details — is merged into the existing paper objects.

        .. note::

           Papers are modified **in-place**.  After calling ``enrich()`` the
           same paper objects passed in will contain the updated metadata.

        Parameters
        ----------
        papers : list[Paper]
            Papers to enrich — typically obtained from
            ``engine.search(...).papers``.
        num_workers : int
            Number of parallel workers.  Defaults to ``1`` (sequential).
            Increase to speed up enrichment of large paper sets.
        timeout : float | None
            Per-request HTTP timeout in seconds.  ``None`` disables the
            timeout.  Defaults to ``10.0``.
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.
            Defaults to ``False``.

        Returns
        -------
        dict[str, int | float]
            Metrics dictionary with at least the following keys:

            * ``total_papers`` — number of papers processed.
            * ``enriched_papers`` — number of papers that gained new metadata.
            * ``doi_enriched_papers`` — subset enriched via CrossRef (DOI
              lookup).
            * ``fetch_error_papers`` — papers where metadata fetch failed.
            * ``no_metadata_papers`` — papers where fetched pages had no
              usable data.
            * ``no_change_papers`` — papers already up-to-date (no new data
              found).
            * ``no_urls_papers`` — papers skipped because they had no known
              URLs.
            * ``runtime_in_seconds`` — wall-clock time of the enrichment
              process.

        See Also
        --------
        findpapers.runners.enrichment_runner.EnrichmentRunner :
            Lower-level class for finer control over the enrichment pipeline.

        Examples
        --------
        Enrich papers right after a search:

        >>> from findpapers import Engine
        >>> engine = Engine()
        >>> result = engine.search("[deep learning]", databases=["arxiv"])
        >>> metrics = engine.enrich(result.papers, num_workers=4)
        >>> print(f"{metrics['enriched_papers']}/{metrics['total_papers']} enriched")
        8/10 enriched

        Chain search, enrichment, and export:

        >>> engine = Engine()
        >>> result = engine.search("[transformers]")
        >>> engine.enrich(result.papers)
        >>> result.to_json("enriched_results.json")
        """
        runner = EnrichmentRunner(
            papers=papers,
            email=self._email,
            num_workers=num_workers,
            timeout=timeout,
        )
        runner.run(verbose=verbose)
        return runner.get_metrics()

    def fetch_paper_by_doi(
        self,
        doi: str,
        *,
        timeout: float | None = 10.0,
        verbose: bool = False,
    ) -> Paper | None:
        """Fetch a single paper by its DOI from CrossRef.

        Queries the CrossRef API for the given DOI and returns a
        :class:`~findpapers.core.paper.Paper` populated with the available
        metadata (title, authors, abstract, source, publication date, etc.).

        The DOI can be provided as a bare identifier (e.g.
        ``"10.1038/nature12373"``) or as a full URL (e.g.
        ``"https://doi.org/10.1038/nature12373"``); the URL prefix is
        stripped automatically.

        Parameters
        ----------
        doi : str
            DOI identifier or DOI URL of the paper to look up.
        timeout : float | None
            HTTP request timeout in seconds.  ``None`` disables the
            timeout.  Defaults to ``10.0``.
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.
            Defaults to ``False``.

        Returns
        -------
        Paper | None
            A :class:`~findpapers.core.paper.Paper` with CrossRef metadata,
            or ``None`` when the DOI is not found or the response cannot be
            parsed into a valid paper.

        Raises
        ------
        ValueError
            If *doi* is empty or blank after stripping whitespace and URL
            prefixes.

        See Also
        --------
        findpapers.runners.doi_lookup_runner.DOILookupRunner :
            Lower-level class for when you need access to runtime metrics or
            want to separate configuration from execution.

        Examples
        --------
        Look up a single paper:

        >>> from findpapers import Engine
        >>> engine = Engine()
        >>> paper = engine.fetch_paper_by_doi("10.1038/nature12373")
        >>> print(paper.title)
        Experimental ...

        Using a full DOI URL:

        >>> paper = engine.fetch_paper_by_doi("https://doi.org/10.1038/nature12373")
        """
        runner = DOILookupRunner(
            doi=doi,
            email=self._email,
            timeout=timeout,
        )
        return runner.run(verbose=verbose)

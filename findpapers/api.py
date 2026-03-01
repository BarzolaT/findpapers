"""Public API for findpapers.

This module exposes the main entry points for searching, downloading, and
enriching academic papers.  Each function is a one-call wrapper that handles
the full pipeline internally.

For advanced use cases (e.g. incremental execution, partial metrics, or
reusing a pre-configured runner), use the underlying runner classes in
:mod:`findpapers.runners` directly.
"""

from __future__ import annotations

from findpapers.core.paper import Paper
from findpapers.core.search import Search
from findpapers.runners.doi_lookup_runner import DOILookupRunner
from findpapers.runners.download_runner import DownloadRunner
from findpapers.runners.enrichment_runner import EnrichmentRunner
from findpapers.runners.search_runner import SearchRunner


def search(
    query: str,
    *,
    databases: list[str] | None = None,
    max_papers_per_database: int | None = None,
    ieee_api_key: str | None = None,
    scopus_api_key: str | None = None,
    pubmed_api_key: str | None = None,
    openalex_api_key: str | None = None,
    openalex_email: str | None = None,
    semantic_scholar_api_key: str | None = None,
    num_workers: int = 1,
    verbose: bool = False,
) -> Search:
    """Search for academic papers across multiple databases.

    Queries one or more academic databases and returns a
    :class:`~findpapers.core.search.Search` object with the collected papers
    already deduplicated and merged.

    Query syntax
    ~~~~~~~~~~~~
    Wrap each search term in square brackets and combine them with
    ``AND``, ``OR``, or ``NOT`` operators.  Optionally prefix a term or group
    with a **filter code** to restrict where it is matched:

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
    ``"pubmed"``, ``"scopus"`` (requires API key), ``"semantic_scholar"``.

    When *databases* is ``None`` every database that does **not** require a
    missing API key is queried automatically.

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
    ieee_api_key : str | None
        IEEE Xplore API key.  Required if ``"ieee"`` is in *databases*.
    scopus_api_key : str | None
        Elsevier / Scopus API key.  Required if ``"scopus"`` is in *databases*.
    pubmed_api_key : str | None
        NCBI PubMed API key.  Optional — increases the rate limit.
    openalex_api_key : str | None
        OpenAlex API key.  Optional.
    openalex_email : str | None
        Contact email for the OpenAlex polite pool.  Highly recommended to
        avoid being rate-limited.
    semantic_scholar_api_key : str | None
        Semantic Scholar API key.  Optional — increases the rate limit.
    num_workers : int
        Number of parallel workers used to query databases concurrently.
        Defaults to ``1`` (sequential).
    verbose : bool
        When ``True``, emit detailed log messages at DEBUG level.
        Defaults to ``False``.

    Returns
    -------
    Search
        A :class:`~findpapers.core.search.Search` object whose ``papers``
        attribute contains the collected :class:`~findpapers.core.paper.Paper`
        instances.  The result can be exported directly via
        ``result.to_json()``, ``result.to_csv()``, or ``result.to_bibtex()``.

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

    >>> import findpapers
    >>> result = findpapers.search("[machine learning]")
    >>> print(f"{len(result.papers)} papers found")
    127 papers found

    Targeted search with filters and database selection:

    >>> result = findpapers.search(
    ...     "ti[transformer] AND abs[attention mechanism]",
    ...     databases=["arxiv", "semantic_scholar"],
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
        ieee_api_key=ieee_api_key,
        scopus_api_key=scopus_api_key,
        pubmed_api_key=pubmed_api_key,
        openalex_api_key=openalex_api_key,
        openalex_email=openalex_email,
        semantic_scholar_api_key=semantic_scholar_api_key,
        num_workers=num_workers,
    )
    return runner.run(verbose=verbose)


def download(
    papers: list[Paper],
    output_directory: str,
    *,
    num_workers: int = 1,
    timeout: float | None = 10.0,
    proxy: str | None = None,
    ssl_verify: bool = True,
    verbose: bool = False,
) -> dict[str, int | float]:
    """Download PDFs for a list of papers.

    For each paper, all known URLs are tried and HTML landing pages are
    followed to resolve the actual PDF link.  Downloaded files are saved to
    *output_directory* with a ``year-title.pdf`` naming scheme.  When a
    download fails the paper is logged to ``download_errors.txt`` inside
    *output_directory*.

    Parameters
    ----------
    papers : list[Paper]
        Papers whose PDFs should be downloaded — typically obtained from
        ``findpapers.search(...).papers``.
    output_directory : str
        Directory where PDF files and the error log will be written.
        Created automatically if it does not exist.
    num_workers : int
        Number of parallel download workers.  Defaults to ``1``
        (sequential).  Increase to speed up bulk downloads.
    timeout : float | None
        Per-request HTTP timeout in seconds.  ``None`` disables the timeout.
    proxy : str | None
        Proxy URL (e.g. ``"http://proxy:8080"``).  When ``None`` the
        ``FINDPAPERS_PROXY`` environment variable is used if set.
    ssl_verify : bool
        Whether to verify SSL certificates.  Set to ``False`` when using
        institutional proxies that perform SSL inspection.
        Defaults to ``True``.
    verbose : bool
        When ``True``, emit detailed log messages at DEBUG level.
        Defaults to ``False``.

    Returns
    -------
    dict[str, int | float]
        Metrics dictionary with at least the following keys:

        * ``total_papers`` — number of papers attempted.
        * ``downloaded_papers`` — number of successfully downloaded PDFs.
        * ``runtime_in_seconds`` — wall-clock time of the download process.

    See Also
    --------
    findpapers.runners.download_runner.DownloadRunner :
        Lower-level class for when you need finer control over the download
        pipeline.

    Examples
    --------
    >>> import findpapers
    >>> result = findpapers.search("[deep learning]", databases=["arxiv"])
    >>> metrics = findpapers.download(result.papers, "./pdfs")
    >>> print(f"{metrics['downloaded_papers']}/{metrics['total_papers']} downloaded")
    8/10 downloaded
    """
    runner = DownloadRunner(
        papers=papers,
        output_directory=output_directory,
        num_workers=num_workers,
        timeout=timeout,
        proxy=proxy,
        ssl_verify=ssl_verify,
    )
    runner.run(verbose=verbose)
    return runner.get_metrics()


def enrich(
    papers: list[Paper],
    *,
    num_workers: int = 1,
    timeout: float | None = 10.0,
    verbose: bool = False,
) -> dict[str, int | float]:
    """Enrich papers with additional metadata from web sources.

    For each paper, metadata is fetched from the CrossRef API (when a DOI is
    available) and by scraping the paper's known URLs.  Found data - such as
    abstracts, keywords, PDF links, citation counts, and source details - is
    merged into the existing paper objects.

    .. note::

       Papers are modified **in-place**.  After calling ``enrich()`` the same
       paper objects passed in will contain the updated metadata.

    Parameters
    ----------
    papers : list[Paper]
        Papers to enrich — typically obtained from
        ``findpapers.search(...).papers``.
    num_workers : int
        Number of parallel workers.  Defaults to ``1`` (sequential).
        Increase to speed up enrichment of large paper sets.
    timeout : float | None
        Per-request HTTP timeout in seconds.  ``None`` disables the timeout.
    verbose : bool
        When ``True``, emit detailed log messages at DEBUG level.
        Defaults to ``False``.

    Returns
    -------
    dict[str, int | float]
        Metrics dictionary with at least the following keys:

        * ``total_papers`` — number of papers processed.
        * ``enriched_papers`` — number of papers that gained new metadata.
        * ``doi_enriched_papers`` — subset enriched via CrossRef (DOI lookup).
        * ``fetch_error_papers`` — papers where metadata fetch failed.
        * ``no_metadata_papers`` — papers where fetched pages had no usable data.
        * ``no_change_papers`` — papers already up-to-date (no new data found).
        * ``no_urls_papers`` — papers skipped because they had no known URLs.
        * ``runtime_in_seconds`` — wall-clock time of the enrichment process.

    See Also
    --------
    findpapers.runners.enrichment_runner.EnrichmentRunner :
        Lower-level class for finer control over the enrichment pipeline.

    Examples
    --------
    Enrich papers right after a search:

    >>> import findpapers
    >>> result = findpapers.search("[deep learning]", databases=["arxiv"])
    >>> metrics = findpapers.enrich(result.papers, num_workers=4)
    >>> print(f"{metrics['enriched_papers']}/{metrics['total_papers']} enriched")
    8/10 enriched

    Chain search, enrichment, and export:

    >>> result = findpapers.search("[transformers]")
    >>> findpapers.enrich(result.papers)
    >>> result.to_json("enriched_results.json")
    """
    runner = EnrichmentRunner(
        papers=papers,
        num_workers=num_workers,
        timeout=timeout,
    )
    runner.run(verbose=verbose)
    return runner.get_metrics()


def fetch_paper_by_doi(
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
    ``"https://doi.org/10.1038/nature12373"``); the URL prefix is stripped
    automatically.

    Parameters
    ----------
    doi : str
        DOI identifier or DOI URL of the paper to look up.
    timeout : float | None
        HTTP request timeout in seconds.  ``None`` uses the ``requests``
        default.  Defaults to ``10.0``.
    verbose : bool
        When ``True``, emit detailed log messages at DEBUG level.
        Defaults to ``False``.

    Returns
    -------
    Paper | None
        A :class:`~findpapers.core.paper.Paper` with CrossRef metadata, or
        ``None`` when the DOI is not found or the response cannot be parsed
        into a valid paper.

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

    >>> import findpapers
    >>> paper = findpapers.fetch_paper_by_doi("10.1038/nature12373")
    >>> print(paper.title)
    Experimental ...

    Using a full DOI URL:

    >>> paper = findpapers.fetch_paper_by_doi("https://doi.org/10.1038/nature12373")
    """
    runner = DOILookupRunner(
        doi=doi,
        timeout=timeout,
    )
    return runner.run(verbose=verbose)

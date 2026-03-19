"""DOILookupRunner: fetches a single paper by its DOI from multiple databases."""

from __future__ import annotations

import logging
from time import perf_counter

from findpapers.connectors.arxiv import ArxivConnector
from findpapers.connectors.connector_base import ConnectorBase
from findpapers.connectors.crossref import CrossRefConnector
from findpapers.connectors.doi_lookup_base import DOILookupConnectorBase
from findpapers.connectors.ieee import IEEEConnector
from findpapers.connectors.openalex import OpenAlexConnector
from findpapers.connectors.pubmed import PubmedConnector
from findpapers.connectors.scopus import ScopusConnector
from findpapers.connectors.semantic_scholar import SemanticScholarConnector
from findpapers.core.paper import Paper
from findpapers.exceptions import InvalidParameterError
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.metadata_parser import DOI_URL_PREFIXES

logger = logging.getLogger(__name__)


class DOILookupRunner:
    """Runner that fetches a single paper by DOI from multiple databases.

    CrossRef is queried first as the canonical DOI registration authority.
    The remaining connectors (OpenAlex, Semantic Scholar, PubMed, arXiv,
    IEEE, Scopus) are then queried in order, and each result is *merged*
    into the base record to fill in any gaps left by the previous sources.

    Connectors that require an API key are silently skipped when no key is
    provided.

    Parameters
    ----------
    doi : str
        A bare DOI identifier (e.g. ``"10.1038/nature12373"``).  Leading
        ``"https://doi.org/"`` prefixes are stripped automatically.
    email : str | None
        Contact email for CrossRef and OpenAlex polite-pool access.  When
        provided those APIs grant higher rate-limits.
    ieee_api_key : str | None
        IEEE Xplore API key.  When omitted IEEE is skipped.
    scopus_api_key : str | None
        Elsevier / Scopus API key.  When omitted Scopus is skipped.
    pubmed_api_key : str | None
        NCBI PubMed API key.  Optional — increases the PubMed rate limit.
    openalex_api_key : str | None
        OpenAlex API key.  Optional — increases the OpenAlex daily quota.
    semantic_scholar_api_key : str | None
        Semantic Scholar API key.  Optional — provides a dedicated quota.
    timeout : float | None
        HTTP request timeout in seconds.  ``None`` uses the ``requests``
        default.

    Raises
    ------
    ValueError
        If *doi* is empty or blank after stripping whitespace and prefix.

    Examples
    --------
    >>> runner = DOILookupRunner(doi="10.1038/nature12373")
    >>> paper = runner.run()
    >>> print(paper.title)
    Experimental ...
    """

    def __init__(
        self,
        doi: str,
        email: str | None = None,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        timeout: float | None = 10.0,
    ) -> None:
        """Initialise DOI lookup configuration.

        Parameters
        ----------
        doi : str
            A bare DOI identifier or full DOI URL.
        email : str | None
            Contact email for CrossRef and OpenAlex polite-pool access.
        ieee_api_key : str | None
            IEEE Xplore API key.
        scopus_api_key : str | None
            Elsevier / Scopus API key.
        pubmed_api_key : str | None
            NCBI PubMed API key.
        openalex_api_key : str | None
            OpenAlex API key.
        semantic_scholar_api_key : str | None
            Semantic Scholar API key.
        timeout : float | None
            HTTP request timeout in seconds.

        Raises
        ------
        ValueError
            If *doi* is empty or blank.
        """
        self._doi = self._sanitize_doi(doi)
        self._timeout = timeout
        self._email = email

        # Build connector instances.  Connectors with optional API keys are
        # always created — they gracefully skip lookups when no key is set.
        self._crossref = CrossRefConnector(email=email)
        self._openalex = OpenAlexConnector(api_key=openalex_api_key, email=email)
        self._semantic_scholar = SemanticScholarConnector(api_key=semantic_scholar_api_key)
        self._pubmed = PubmedConnector(api_key=pubmed_api_key)
        self._arxiv = ArxivConnector()
        # IEEE and Scopus are only created when a key is provided — their
        # constructors raise InvalidParameterError otherwise.
        self._ieee = IEEEConnector(api_key=ieee_api_key) if ieee_api_key else None
        self._scopus = ScopusConnector(api_key=scopus_api_key) if scopus_api_key else None

        if timeout is not None:
            for connector in self._all_connectors:
                connector._timeout = timeout

        self._result: Paper | None = None

    @property
    def _all_connectors(self) -> list[ConnectorBase]:
        """Return all connector instances in lookup priority order.

        Returns
        -------
        list
            Connector instances ordered: CrossRef, OpenAlex, Semantic
            Scholar, PubMed, arXiv, and optionally IEEE and Scopus when
            their API keys were provided at construction time.
        """
        connectors = [
            self._crossref,
            self._openalex,
            self._semantic_scholar,
            self._pubmed,
            self._arxiv,
            self._ieee,
            self._scopus,
        ]
        return [c for c in connectors if c is not None]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False) -> Paper | None:
        """Execute the DOI lookup across all configured databases.

        Queries each database in order (CrossRef → OpenAlex → Semantic Scholar
        → PubMed → arXiv → IEEE → Scopus).  The first result becomes the
        *base* paper; every subsequent result is merged into it so that gaps
        from one source are filled by another.

        Parameters
        ----------
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.

        Returns
        -------
        Paper | None
            A :class:`~findpapers.core.paper.Paper` populated with the best
            available metadata from all queried sources, or ``None`` when no
            database found a paper for the given DOI.
        """
        if verbose:
            configure_verbose_logging()
            logger.info("=== DOILookupRunner ===")
            logger.info("DOI: %s", self._doi)
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("=======================")

        start = perf_counter()

        base_paper: Paper | None = None

        try:
            base_paper = self._run_connector(self._crossref, "CrossRef", None, verbose=verbose)

            base_paper = self._run_connector(self._arxiv, "arXiv", base_paper, verbose=verbose)
            base_paper = self._run_connector(self._ieee, "IEEE", base_paper, verbose=verbose)
            base_paper = self._run_connector(self._pubmed, "PubMed", base_paper, verbose=verbose)
            base_paper = self._run_connector(self._scopus, "Scopus", base_paper, verbose=verbose)
            base_paper = self._run_connector(
                self._semantic_scholar, "Semantic Scholar", base_paper, verbose=verbose
            )
            base_paper = self._run_connector(
                self._openalex, "OpenAlex", base_paper, verbose=verbose
            )

        finally:
            for connector in self._all_connectors:
                connector.close()

        self._result = base_paper
        runtime = perf_counter() - start

        if verbose:
            if self._result is not None:
                dbs = ", ".join(sorted(self._result.databases or []))
                logger.info("DOI lookup found — databases: %s (%.2f s)", dbs, runtime)
            else:
                logger.info("DOI lookup not found (%.2f s)", runtime)

        return self._result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_connector(
        self,
        connector: DOILookupConnectorBase | None,
        name: str,
        base_paper: Paper | None,
        *,
        verbose: bool,
    ) -> Paper | None:
        """Query a connector and merge its result into *base_paper*.

        If *connector* is ``None`` (key was not provided at runner construction)
        the method returns *base_paper* unchanged.

        If the connector returns a paper and *base_paper* already exists,
        the new paper is merged into the base (which enriches the base with
        any additional metadata from this source).  If *base_paper* is
        ``None`` the new paper becomes the base.

        Parameters
        ----------
        connector : object
            Any connector that exposes ``fetch_paper_by_doi(doi) -> Paper | None``.
        name : str
            Human-readable connector name for logging.
        base_paper : Paper | None
            The accumulated result so far (may be ``None``).
        verbose : bool
            Whether verbose logging is active.

        Returns
        -------
        Paper | None
            Updated base paper (with additional databases added), or the
            original *base_paper* when this connector returns nothing new.
        """
        if verbose:
            logger.info("Querying %s…", name)
        if connector is None:
            if verbose:
                logger.info("  %s: skipped (no API key)", name)
            return base_paper
        try:
            paper = connector.fetch_paper_by_doi(self._doi)
        except Exception:
            logger.debug("%s lookup failed for DOI %s.", name, self._doi, exc_info=True)
            paper = None

        if paper is None:
            if verbose:
                logger.info("  %s: not found", name)
            return base_paper

        if verbose:
            logger.info("  %s: found", name)

        if base_paper is None:
            return paper

        # Merge the new paper's data into the existing base record so the
        # accumulated result benefits from every source's metadata.
        base_paper.merge(paper)
        return base_paper

    @staticmethod
    def _sanitize_doi(doi: str) -> str:
        """Strip whitespace and common URL prefixes from a DOI string.

        Parameters
        ----------
        doi : str
            Raw DOI input from the user.

        Returns
        -------
        str
            Bare DOI identifier.

        Raises
        ------
        InvalidParameterError
            If the result is empty after sanitization.
        """
        cleaned = doi.strip()
        for prefix in DOI_URL_PREFIXES:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :]
                break
        cleaned = cleaned.strip()
        if not cleaned:
            raise InvalidParameterError("DOI must not be empty.")
        return cleaned

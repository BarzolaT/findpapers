"""GetRunner: fetches a single paper by identifier (URL or DOI) from multiple sources."""

from __future__ import annotations

import logging
import re
from time import perf_counter

from findpapers.connectors import DOI_LOOKUP_REGISTRY, URL_LOOKUP_REGISTRY
from findpapers.connectors.connector_base import ConnectorBase
from findpapers.connectors.doi_lookup_base import DOILookupConnectorBase
from findpapers.connectors.url_lookup_base import URLLookupConnectorBase
from findpapers.connectors.web_scraping import WebScrapingConnector
from findpapers.core.paper import Paper
from findpapers.core.search_result import Database
from findpapers.exceptions import InvalidParameterError
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.normalization import DOI_URL_PREFIXES

logger = logging.getLogger(__name__)

# Matches doi.org and dx.doi.org redirect URLs.  These bypass HTML scraping
# and go straight to the DOI-based API connectors.
_DOI_ORG_URL_RE: re.Pattern[str] = re.compile(r"^https?://(?:dx\.)?doi\.org/", re.IGNORECASE)

# All valid ``databases`` values accepted by :class:`GetRunner`.
# ``"web_scraping"`` is a special toggle not backed by a connector class.
GET_DATABASES: frozenset[str] = frozenset(
    {db.value for db in DOI_LOOKUP_REGISTRY} | {"web_scraping"}
)


class GetRunner:
    """Runner that fetches a single paper by URL or DOI from multiple sources.

    The pipeline runs in two complementary stages that are no longer mutually
    exclusive:

    **Stage 1 — web scraping** (landing-page URLs only, requires ``"web_scraping"`` in *databases*):
        :class:`~findpapers.connectors.web_scraping.WebScrapingConnector` is
        tried first.  If the URL belongs to a known database (arXiv, PubMed,
        OpenAlex, Semantic Scholar, IEEE) the call is delegated to that
        database's API connector instead of performing HTML scraping.  Any DOI
        found in the result is carried forward to Stage 2.

    **Stage 2 — DOI lookup** (requires a DOI to be available):
        CrossRef is queried first as the canonical DOI registration authority
        (when ``"crossref"`` is in *databases*).
        The remaining connectors (arXiv, IEEE, PubMed, Scopus, Semantic
        Scholar, OpenAlex) follow in order, and each result is *merged* into
        the base paper so that gaps from one source are filled by another.
        The CrossRef URL is preserved as the final canonical URL when
        available.

    For bare DOI inputs (or ``doi.org`` redirect URLs) Stage 1 is skipped and
    the lookup proceeds directly to Stage 2.

    Parameters
    ----------
    identifier : str
        A bare DOI (e.g. ``"10.1038/nature12373"``), a doi.org redirect URL
        (e.g. ``"https://doi.org/10.1038/nature12373"``), or a paper
        landing-page URL (e.g. ``"https://arxiv.org/abs/1706.03762"``).
    email : str | None
        Contact email for CrossRef and OpenAlex polite-pool access.  When
        provided those APIs grant higher rate-limits.
    databases : list[str] | None
        Sources to consult when looking up the paper.  When ``None`` all
        sources are used.  Pass a list to enable only the specified ones.
        Accepted values: ``"arxiv"``, ``"crossref"``, ``"ieee"``,
        ``"openalex"``, ``"pubmed"``, ``"scopus"``,
        ``"semantic_scholar"``, ``"web_scraping"``.
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
    proxy : str | None
        Optional HTTP/HTTPS proxy URL for web scraping requests.
    ssl_verify : bool
        Whether to verify SSL certificates.  Set to ``False`` only when
        working behind institutional proxies that perform SSL inspection.
        Defaults to ``True``.

    Raises
    ------
    InvalidParameterError
        If *identifier* is a bare DOI that is empty or blank after stripping
        whitespace and URL prefixes.
    InvalidParameterError
        If *databases* is an empty list or contains unknown database names.

    Examples
    --------
    Fetch by bare DOI:

    >>> runner = GetRunner(identifier="10.1038/nature12373")
    >>> paper = runner.run()

    Fetch by landing-page URL (scrapes first, then enriches via DOI if found):

    >>> runner = GetRunner(identifier="https://arxiv.org/abs/1706.03762")
    >>> paper = runner.run()
    """

    def __init__(
        self,
        identifier: str,
        email: str | None = None,
        databases: list[str] | None = None,
        ieee_api_key: str | None = None,
        scopus_api_key: str | None = None,
        pubmed_api_key: str | None = None,
        openalex_api_key: str | None = None,
        semantic_scholar_api_key: str | None = None,
        timeout: float | None = 10.0,
        proxy: str | None = None,
        ssl_verify: bool = True,
    ) -> None:
        """Initialise the runner with an identifier and connection settings.

        Parameters
        ----------
        identifier : str
            A bare DOI, doi.org redirect URL, or paper landing-page URL.
        email : str | None
            Contact email for CrossRef and OpenAlex polite-pool access.
        databases : list[str] | None
            Sources to consult when looking up the paper.  When ``None``
            all sources are used.  Pass a list to enable only the
            specified ones.  Accepted values: ``"arxiv"``,
            ``"crossref"``, ``"ieee"``, ``"openalex"``, ``"pubmed"``,
            ``"scopus"``, ``"semantic_scholar"``, ``"web_scraping"``.
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
        proxy : str | None
            Optional HTTP/HTTPS proxy URL.
        ssl_verify : bool
            Whether to verify SSL certificates.

        Raises
        ------
        InvalidParameterError
            If *identifier* looks like a bare DOI (not a URL) but is empty
            after stripping.
        InvalidParameterError
            If *databases* is an empty list or contains unknown database names.
        """
        self._identifier = identifier
        self._timeout = timeout

        # Validate and resolve the active databases filter.
        if databases is not None and len(databases) == 0:
            raise InvalidParameterError(
                "databases must not be an empty list. Pass None to select all available databases."
            )
        if databases is not None:
            normalised = [db.strip().lower() for db in databases]
            unknown = [db for db in normalised if db not in GET_DATABASES]
            if unknown:
                raise InvalidParameterError(
                    f"Unknown database(s): {', '.join(unknown)}. "
                    f"Accepted values: {', '.join(sorted(GET_DATABASES))}"
                )
            active_dbs: frozenset[str] = frozenset(normalised)
        else:
            active_dbs = GET_DATABASES

        # Per-source credentials forwarded to each connector at construction time.
        _credentials: dict[Database, dict[str, object]] = {
            Database.CROSSREF: {"email": email},
            Database.ARXIV: {},
            Database.IEEE: {"api_key": ieee_api_key},
            Database.OPENALEX: {"api_key": openalex_api_key, "email": email},
            Database.PUBMED: {"api_key": pubmed_api_key},
            Database.SCOPUS: {"api_key": scopus_api_key},
            Database.SEMANTIC_SCHOLAR: {"api_key": semantic_scholar_api_key},
        }
        # Sources whose connector requires an API key to function.
        _key_required: frozenset[Database] = frozenset({Database.IEEE, Database.SCOPUS})

        # Build DOI-lookup connectors from the registry.
        _doi_map: dict[Database, DOILookupConnectorBase] = {}
        for _source, _cls in DOI_LOOKUP_REGISTRY.items():
            if _source.value not in active_dbs:
                continue
            _creds = _credentials.get(_source, {})
            if _source in _key_required and not _creds.get("api_key"):
                continue
            _doi_map[_source] = _cls(**_creds)

        self._crossref: DOILookupConnectorBase | None = _doi_map.get(Database.CROSSREF)
        self._arxiv: DOILookupConnectorBase | None = _doi_map.get(Database.ARXIV)
        self._ieee: DOILookupConnectorBase | None = _doi_map.get(Database.IEEE)
        self._openalex: DOILookupConnectorBase | None = _doi_map.get(Database.OPENALEX)
        self._pubmed: DOILookupConnectorBase | None = _doi_map.get(Database.PUBMED)
        self._scopus: DOILookupConnectorBase | None = _doi_map.get(Database.SCOPUS)
        self._semantic_scholar: DOILookupConnectorBase | None = _doi_map.get(
            Database.SEMANTIC_SCHOLAR
        )

        if timeout is not None:
            for connector in self._doi_connectors:
                connector._timeout = timeout

        # Build URL-lookup connectors for the web scraper.  These are separate
        # instances so the scraper can use them independently from the DOI
        # connectors above.
        url_lookup: list[URLLookupConnectorBase] = []
        for _url_source, _url_cls in URL_LOOKUP_REGISTRY.items():
            if _url_source.value not in active_dbs:
                continue
            _url_creds = _credentials.get(_url_source, {})
            if _url_source in _key_required and not _url_creds.get("api_key"):
                continue
            url_lookup.append(_url_cls(**_url_creds))

        self._scraper: WebScrapingConnector | None = (
            WebScrapingConnector(
                proxy=proxy,
                ssl_verify=ssl_verify,
                url_lookup_connectors=url_lookup,
            )
            if "web_scraping" in active_dbs
            else None
        )
        if timeout is not None and self._scraper is not None:
            self._scraper._timeout = timeout

        self._result: Paper | None = None

    @property
    def _doi_connectors(self) -> list[ConnectorBase]:
        """Return all DOI-based connector instances in lookup priority order.

        Returns
        -------
        list[ConnectorBase]
            Connectors ordered: CrossRef (when enabled), OpenAlex, Semantic
            Scholar, PubMed, arXiv, and optionally IEEE and Scopus when their
            API keys were provided at construction time.
        """
        connectors: list[ConnectorBase | None] = [
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
        """Execute the full lookup pipeline for the configured identifier.

        The pipeline runs two complementary stages:

        1. **URL stage** (landing-page URLs only): web scraping is performed,
           potentially yielding an initial paper and its DOI.
        2. **DOI stage**: CrossRef and all other API connectors are queried
           using the available DOI (from Stage 1 or the original identifier),
           and their results are merged into the base paper.

        For bare DOI inputs or ``doi.org`` URLs, Stage 1 is skipped.

        Parameters
        ----------
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.
            Defaults to ``False``.

        Returns
        -------
        Paper | None
            A :class:`~findpapers.core.paper.Paper` populated with the best
            available metadata from all queried sources, or ``None`` when no
            source found a match.
        """
        if verbose:
            configure_verbose_logging()
            logger.info("=== GetRunner ===")
            logger.info("Identifier: %s", self._identifier)
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("=================")

        start = perf_counter()

        base_paper: Paper | None = None
        doi: str | None = None

        try:
            if self._is_landing_page_url(self._identifier):
                if self._scraper is not None:
                    # Stage 1: try URL-API connectors first; fall back to HTML scraping.
                    if verbose:
                        logger.info("Stage 1 — web scraping: %s", self._identifier)
                    try:
                        base_paper = self._scraper.fetch_paper_from_url(
                            self._identifier, timeout=self._timeout
                        )
                    except Exception:
                        logger.debug(
                            "Web scraping failed for URL %s.", self._identifier, exc_info=True
                        )
                    doi = base_paper.doi if base_paper is not None else None
                    if verbose:
                        if doi:
                            logger.info("  Scraped DOI: %s", doi)
                        else:
                            logger.info("  No DOI found — Stage 2 will be skipped.")
                else:
                    if verbose:
                        logger.info(
                            "Stage 1 — web scraping: skipped (disabled via databases filter)"
                        )
            else:
                # Bare DOI or doi.org URL: strip prefix and go straight to Stage 2.
                doi = self._sanitize_doi(self._identifier)
                # When web scraping is enabled, follow the doi.org redirect to the
                # landing page and extract metadata via HTML scraping.  curl_cffi
                # follows HTTP redirects automatically, so the scraper processes
                # the actual publisher or repository page.
                if self._scraper is not None and doi:
                    doi_redirect_url = f"https://doi.org/{doi}"
                    if verbose:
                        logger.info("Stage 1 — web scraping via DOI URL: %s", doi_redirect_url)
                    try:
                        base_paper = self._scraper.fetch_paper_from_url(
                            doi_redirect_url, timeout=self._timeout
                        )
                    except Exception:
                        logger.debug(
                            "Web scraping failed for DOI URL %s.",
                            doi_redirect_url,
                            exc_info=True,
                        )
                    if verbose:
                        if base_paper is not None:
                            logger.info("  Scraped: %s", base_paper.title)
                        else:
                            logger.info("  No paper found via web scraping.")

            if doi is None:
                # No DOI available; return whatever the scraper found (may be None).
                self._result = base_paper
                return self._result

            # Stage 2: DOI-based lookup — CrossRef first, then all others.
            if verbose:
                logger.info("Stage 2 — DOI lookup: %s", doi)

            crossref_paper = self._run_doi_connector(
                self._crossref, "CrossRef", doi, verbose=verbose
            )
            # Preserve the CrossRef URL before subsequent merges can overwrite it.
            # Paper.merge() picks the longer string, which could replace a short but
            # authoritative CrossRef URL with a lengthier one from another source.
            crossref_url: str | None = crossref_paper.url if crossref_paper is not None else None

            if crossref_paper is not None:
                if base_paper is None:
                    base_paper = crossref_paper
                else:
                    base_paper.merge(crossref_paper)

            # Iterate through the remaining connectors in priority order.
            for connector, name in (
                (self._arxiv, "arXiv"),
                (self._ieee, "IEEE"),
                (self._pubmed, "PubMed"),
                (self._scopus, "Scopus"),
                (self._semantic_scholar, "Semantic Scholar"),
                (self._openalex, "OpenAlex"),
            ):
                base_paper = self._run_and_merge(connector, name, doi, base_paper, verbose=verbose)

            # Restore CrossRef URL as the final canonical URL when available.
            if base_paper is not None and crossref_url is not None:
                base_paper.url = crossref_url

        finally:
            for doi_connector in self._doi_connectors:
                doi_connector.close()
            if self._scraper is not None:
                self._scraper.close()

        self._result = base_paper
        runtime = perf_counter() - start

        if verbose:
            if self._result is not None:
                dbs = ", ".join(sorted(self._result.databases or []))
                logger.info("Lookup found — databases: %s (%.2f s)", dbs, runtime)
            else:
                logger.info("Lookup not found (%.2f s)", runtime)

        return self._result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_doi_connector(
        self,
        connector: DOILookupConnectorBase | None,
        name: str,
        doi: str,
        *,
        verbose: bool,
    ) -> Paper | None:
        """Query one DOI connector and return its result without merging.

        Parameters
        ----------
        connector : DOILookupConnectorBase | None
            Connector to query.  When ``None`` the method returns ``None``
            immediately (connector was not initialised due to a missing API
            key).
        name : str
            Human-readable connector name used in log messages.
        doi : str
            Bare DOI to look up.
        verbose : bool
            Whether verbose logging is active.

        Returns
        -------
        Paper | None
            Paper returned by the connector, or ``None`` when the connector
            is absent, the DOI is not found, or an error occurs.
        """
        if verbose:
            logger.info("Querying %s…", name)
        if connector is None:
            if verbose:
                logger.info("  %s: skipped", name)
            return None
        try:
            paper = connector.fetch_paper_by_doi(doi)
        except Exception:
            logger.debug("%s lookup failed for DOI %s.", name, doi, exc_info=True)
            paper = None
        if paper is None:
            if verbose:
                logger.info("  %s: not found", name)
        elif verbose:
            logger.info("  %s: found", name)
        return paper

    def _run_and_merge(
        self,
        connector: DOILookupConnectorBase | None,
        name: str,
        doi: str,
        base_paper: Paper | None,
        *,
        verbose: bool,
    ) -> Paper | None:
        """Query a connector and merge its result into *base_paper*.

        If the connector returns a paper and *base_paper* already exists,
        the new paper is merged into the base so that each subsequent source
        enriches the accumulated result.  If *base_paper* is ``None`` the
        new paper becomes the base.

        Parameters
        ----------
        connector : DOILookupConnectorBase | None
            Connector to query.
        name : str
            Human-readable connector name used in log messages.
        doi : str
            Bare DOI to look up.
        base_paper : Paper | None
            The accumulated result so far (may be ``None``).
        verbose : bool
            Whether verbose logging is active.

        Returns
        -------
        Paper | None
            Updated *base_paper* with the connector's data merged in, or the
            original *base_paper* when the connector returns nothing new.
        """
        paper = self._run_doi_connector(connector, name, doi, verbose=verbose)
        if paper is None:
            return base_paper
        if base_paper is None:
            return paper
        base_paper.merge(paper)
        return base_paper

    @staticmethod
    def _is_landing_page_url(identifier: str) -> bool:
        """Return ``True`` when *identifier* is a URL but not a doi.org redirect.

        Parameters
        ----------
        identifier : str
            The identifier string to classify.

        Returns
        -------
        bool
            ``True`` for ``http://`` and ``https://`` URLs that are not
            ``doi.org`` or ``dx.doi.org`` redirects.
        """
        return identifier.startswith(("http://", "https://")) and not _DOI_ORG_URL_RE.match(
            identifier
        )

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

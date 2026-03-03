"""DOILookupRunner: fetches a single paper by its DOI via CrossRef."""

from __future__ import annotations

import logging
from time import perf_counter

from findpapers.connectors.crossref import CrossRefConnector
from findpapers.core.paper import Paper
from findpapers.utils.logging_config import configure_verbose_logging

logger = logging.getLogger(__name__)


class DOILookupRunner:
    """Runner that fetches a single paper by DOI using the CrossRef API.

    The runner queries CrossRef's ``/works/{doi}`` endpoint and converts the
    response into a :class:`~findpapers.core.paper.Paper` instance.

    Parameters
    ----------
    doi : str
        A bare DOI identifier (e.g. ``"10.1038/nature12373"``).  Leading
        ``"https://doi.org/"`` prefixes are stripped automatically.
    email : str | None
        Contact email for CrossRef polite-pool access.  When provided
        CrossRef grants higher rate-limits.
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

    # Common DOI URL prefixes to strip so that callers can pass either the
    # bare DOI or the full URL.
    _DOI_URL_PREFIXES = (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
    )

    def __init__(
        self,
        doi: str,
        email: str | None = None,
        timeout: float | None = 10.0,
    ) -> None:
        """Initialise DOI lookup configuration.

        Parameters
        ----------
        doi : str
            A bare DOI identifier or full DOI URL.
        email : str | None
            Contact email for CrossRef polite-pool access.
        timeout : float | None
            HTTP request timeout in seconds.

        Raises
        ------
        ValueError
            If *doi* is empty or blank.
        """
        self._doi = self._sanitize_doi(doi)
        self._timeout = timeout
        self._connector = CrossRefConnector(email=email)
        self._result: Paper | None = None
        self._executed = False
        self._runtime: float = 0.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False) -> Paper | None:
        """Execute the DOI lookup and return the paper.

        Parameters
        ----------
        verbose : bool
            When ``True``, emit detailed log messages at DEBUG level.

        Returns
        -------
        Paper | None
            A :class:`~findpapers.core.paper.Paper` populated with CrossRef
            metadata, or ``None`` when the DOI is not found or the response
            cannot be parsed into a valid paper.
        """
        if verbose:
            configure_verbose_logging()
            logger.info("=== DOILookupRunner ===")
            logger.info("DOI: %s", self._doi)
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("=======================")

        start = perf_counter()

        try:
            work = self._connector.fetch_work(self._doi)
            if work is not None:
                self._result = self._connector.build_paper(work)
            else:
                self._result = None
        finally:
            self._connector.close()

        self._runtime = perf_counter() - start
        self._executed = True

        if verbose:
            status = "found" if self._result is not None else "not found"
            logger.info("DOI lookup %s (%.2f s)", status, self._runtime)

        return self._result

    def get_result(self) -> Paper | None:
        """Return the paper obtained from the last :meth:`run` call.

        Returns
        -------
        Paper | None
            The paper, or ``None`` if the DOI was not found.

        Raises
        ------
        RuntimeError
            If :meth:`run` has not been called yet.
        """
        if not self._executed:
            raise RuntimeError("DOILookupRunner has not been executed yet.")
        return self._result

    def get_runtime(self) -> float:
        """Return the wall-clock runtime of the last :meth:`run` call.

        Returns
        -------
        float
            Runtime in seconds.

        Raises
        ------
        RuntimeError
            If :meth:`run` has not been called yet.
        """
        if not self._executed:
            raise RuntimeError("DOILookupRunner has not been executed yet.")
        return self._runtime

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @classmethod
    def _sanitize_doi(cls, doi: str) -> str:
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
        ValueError
            If the result is empty after sanitization.
        """
        cleaned = doi.strip()
        for prefix in cls._DOI_URL_PREFIXES:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :]
                break
        cleaned = cleaned.strip()
        if not cleaned:
            raise ValueError("DOI must not be empty.")
        return cleaned

"""Abstract base class for academic database searchers."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import urlencode

import requests

if TYPE_CHECKING:
    from findpapers.core.paper import Paper
    from findpapers.core.query import Query
    from findpapers.query.builder import QueryBuilder, QueryValidationResult

logger = logging.getLogger(__name__)

QUERY_COMBINATIONS_WARNING_THRESHOLD = 20

# Parameter names (compared case-insensitively) that carry API credentials
# and must be redacted before logging.
_SENSITIVE_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "api_key",
        "apikey",
        "x-api-key",
        "x-els-apikey",
        "x-api-key",
    }
)


class SearcherBase(ABC):
    """Abstract base class for academic database searchers.

    Subclasses implement the search logic for a specific database and receive
    a database-specific ``QueryBuilder`` via dependency injection. Each
    searcher is responsible for:

    1. Validating the query against the database capabilities.
    2. Converting the query to the database-specific format.
    3. Executing HTTP requests with proper rate limiting.
    4. Parsing the API responses into :class:`~findpapers.core.paper.Paper` objects.
    """

    # Shared rate-limiter state; assignment in _rate_limit creates an instance
    # attribute that shadows this default, so multiple instances are isolated.
    _last_request_time: float = 0.0

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-friendly database name used in logs and metrics.

        Returns
        -------
        str
            Database identifier.
        """

    @property
    @abstractmethod
    def query_builder(self) -> "QueryBuilder":
        """Return the database-specific query builder.

        Returns
        -------
        QueryBuilder
            Builder used to validate and convert queries.
        """

    @abstractmethod
    def _fetch_papers(
        self,
        query: "Query",
        max_papers: Optional[int],
        progress_callback: Optional[Callable[[int, Optional[int]], None]],
    ) -> List["Paper"]:
        """Fetch papers from the database.

        Subclasses implement HTTP requests, rate limiting, pagination and
        response parsing here.

        Parameters
        ----------
        query : Query
            Pre-validated query object.
        max_papers : int | None
            Maximum papers to retrieve.  ``None`` means unlimited.
        progress_callback : Callable[[int, int | None], None] | None
            Optional callback invoked after each page / item with
            ``(items_processed, total_or_none)``.  ``items_processed`` counts
            every candidate item attempted (regardless of whether it was
            successfully parsed), so the bar always reaches ``total`` even
            when some items fail to parse.

        Returns
        -------
        list[Paper]
            Retrieved papers.

        Raises
        ------
        Exception
            Implementations may raise on network or parsing failures.
        """

    @property
    @abstractmethod
    def min_request_interval(self) -> float:
        """Minimum number of seconds that must elapse between consecutive HTTP requests.

        Returns
        -------
        float
            Interval in seconds.
        """

    @property
    def is_available(self) -> bool:
        """Return ``True`` if the searcher is properly configured and ready to use.

        Searchers that require an API key override this property to return
        ``False`` when no key has been provided, so the runner can skip them
        gracefully instead of failing at query time.

        Returns
        -------
        bool
            ``True`` by default; ``False`` when a required credential is absent.
        """
        return True

    def _rate_limit(self) -> None:
        """Enforce the minimum interval between HTTP requests.

        Sleeps only the remaining time needed so that ``min_request_interval``
        seconds have elapsed since the last request completed.
        """
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

    def _prepare_params(self, params: dict) -> dict:
        """Augment query parameters before the request is sent.

        The default implementation returns *params* unchanged.  Subclasses
        override this to inject API keys or other credentials into the query
        string.

        Parameters
        ----------
        params : dict
            Raw query parameters supplied by the caller.

        Returns
        -------
        dict
            Augmented parameters.
        """
        return params

    def _prepare_headers(self, headers: dict) -> dict:
        """Augment HTTP headers before the request is sent.

        The default implementation returns *headers* unchanged.  Subclasses
        override this to inject API keys, ``Accept`` values, or custom
        ``User-Agent`` strings.

        Parameters
        ----------
        headers : dict
            Raw HTTP headers supplied by the caller.

        Returns
        -------
        dict
            Augmented headers.
        """
        return headers

    def _get(
        self,
        url: str,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        """Perform a rate-limited, logged GET request.

        Calls :meth:`_prepare_params` and :meth:`_prepare_headers` so
        subclasses can inject credentials without duplicating the
        rate-limiting and logging boilerplate.

        Parameters
        ----------
        url : str
            Target URL.
        params : dict | None
            Query parameters (before credential injection).
        headers : dict | None
            HTTP headers (before credential injection).

        Returns
        -------
        requests.Response
            HTTP response.

        Raises
        ------
        requests.HTTPError
            On non-2xx status codes.
        """
        prepared_params = self._prepare_params(dict(params) if params else {})
        prepared_headers = self._prepare_headers(dict(headers) if headers else {})
        self._rate_limit()
        self._log_request(url, prepared_params or None)
        response = requests.get(
            url,
            params=prepared_params or None,
            headers=prepared_headers or None,
            timeout=30,
        )
        self._last_request_time = time.monotonic()
        response.raise_for_status()
        self._log_response(response)
        return response

    def _log_request(self, url: str, params: Optional[dict] = None) -> None:
        """Log an outgoing HTTP GET request at ``DEBUG`` level.

        API keys and other sensitive parameters are replaced with ``"***"``
        so that credentials are never written to logs.

        Parameters
        ----------
        url : str
            Base request URL (without query string).
        params : dict | None
            Query parameters to be sent with the request.
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        if params:
            safe_params = {
                k: "***" if k.lower() in _SENSITIVE_PARAM_NAMES else v for k, v in params.items()
            }
            full_url = f"{url}?{urlencode(safe_params)}"
        else:
            full_url = url
        logger.debug("[%s] GET %s", self.name, full_url)

    def _log_response(self, response: requests.Response) -> None:
        """Log a summary of an HTTP response at ``DEBUG`` level.

        Logs the HTTP status code, content-type header, and body size so that
        verbose sessions can trace what each request returned without printing
        the full body.

        Parameters
        ----------
        response : requests.Response
            The completed HTTP response to summarise.
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        status = f"{response.status_code} {response.reason}"
        content_type = response.headers.get("Content-Type", "unknown").split(";")[0].strip()
        size = len(response.content)
        logger.debug(
            "[%s] <- %s | content-type: %s | %d bytes",
            self.name,
            status,
            content_type,
            size,
        )

    def search(
        self,
        query: "Query",
        max_papers: Optional[int] = None,
        progress_callback: Optional[Callable[[int, Optional[int]], None]] = None,
    ) -> List["Paper"]:
        """Execute search and return a list of papers.

        Validates the query first.  If validation fails the search is skipped
        for this database and an empty list is returned (warning is logged).

        Parameters
        ----------
        query : Query
            Parsed query object.
        max_papers : int | None
            Maximum number of papers to return.
        progress_callback : Callable[[int, int | None], None] | None
            Progress callback called as ``callback(current, total_or_none)``.

        Returns
        -------
        list[Paper]
            Retrieved papers, or empty list when query is incompatible.
        """
        validation: QueryValidationResult = self.query_builder.validate_query(query)

        if not validation.is_valid:
            logger.warning(
                "Search on '%s' aborted: incompatible query. %s",
                self.name,
                validation.error_message or "",
            )
            return []

        try:
            return self._fetch_papers(query, max_papers, progress_callback)
        except Exception:
            logger.exception("Unexpected error while searching '%s'.", self.name)
            return []

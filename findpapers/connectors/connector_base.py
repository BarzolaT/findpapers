"""Abstract base class for external API connectors.

Provides shared HTTP infrastructure — rate limiting, credential injection,
request/response logging — so that every module that talks to an external
service inherits a consistent, production-ready networking layer.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlencode

import requests

from findpapers.utils.http_headers import get_browser_headers

logger = logging.getLogger(__name__)

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

# Header names (compared case-insensitively) that carry API credentials
# and must be redacted before logging.
_SENSITIVE_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "x-els-apikey",
        "x-api-key",
        "authorization",
    }
)


class ConnectorBase(ABC):
    """Abstract base class for external API connectors.

    Provides rate-limited HTTP helpers (``_get`` / ``_post``), automatic
    credential injection via ``_prepare_params`` / ``_prepare_headers``,
    and debug-level request/response logging with sensitive-parameter
    redaction.

    Subclasses must implement :attr:`name` and :attr:`min_request_interval`.
    """

    # Shared rate-limiter state; assignment in _rate_limit creates an instance
    # attribute that shadows this default, so multiple instances are isolated.
    _last_request_time: float = 0.0

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable connector identifier used in log messages.

        Returns
        -------
        str
            Connector name (e.g. ``"arxiv"``, ``"crossref"``).
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
        """Return ``True`` if the connector is properly configured and ready to use.

        Connectors that require an API key override this property to return
        ``False`` when no key has been provided, so callers can skip them
        gracefully instead of failing at request time.

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
        # Merge browser headers as defaults so every outgoing request carries
        # a realistic User-Agent even when the subclass does not set one.
        # Subclass-provided values always take precedence.
        return {**get_browser_headers(), **headers}

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
        self._log_request(url, prepared_params or None, headers=prepared_headers)
        response = requests.get(
            url,
            params=prepared_params or None,
            headers=prepared_headers or None,
            timeout=30,
        )
        self._last_request_time = time.monotonic()
        self._log_response(response)
        response.raise_for_status()
        return response

    def _post(
        self,
        url: str,
        json_body: Optional[dict | list] = None,
        params: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> requests.Response:
        """Perform a rate-limited, logged POST request.

        Mirrors :meth:`_get` but sends a JSON body via ``requests.post``.
        Calls :meth:`_prepare_params` and :meth:`_prepare_headers` for
        credential injection and browser-header defaults.

        Parameters
        ----------
        url : str
            Target URL.
        json_body : dict | list | None
            JSON-serialisable payload for the request body.
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
        self._log_request(url, prepared_params or None, method="POST", headers=prepared_headers)
        response = requests.post(
            url,
            json=json_body,
            params=prepared_params or None,
            headers=prepared_headers or None,
            timeout=30,
        )
        self._last_request_time = time.monotonic()
        self._log_response(response)
        response.raise_for_status()
        return response

    def _log_request(
        self,
        url: str,
        params: Optional[dict] = None,
        method: str = "GET",
        headers: Optional[dict] = None,
    ) -> None:
        """Log an outgoing HTTP request at ``DEBUG`` level.

        API keys and other sensitive parameters and headers are replaced with
        ``"***"`` so that credentials are never written to logs.

        Parameters
        ----------
        url : str
            Base request URL (without query string).
        params : dict | None
            Query parameters to be sent with the request.
        method : str
            HTTP method (e.g. ``"GET"`` or ``"POST"``).
        headers : dict | None
            HTTP headers to be sent with the request.
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
        logger.debug("[%s] %s %s", self.name, method, full_url)
        if headers:
            safe_headers = {
                k: "***" if k.lower() in _SENSITIVE_HEADER_NAMES else v for k, v in headers.items()
            }
            logger.debug("[%s] headers: %s", self.name, safe_headers)

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

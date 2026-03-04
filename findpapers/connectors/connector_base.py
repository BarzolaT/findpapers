"""Abstract base class for external API connectors.

Provides shared HTTP infrastructure — rate limiting, credential injection,
request/response logging — so that every module that talks to an external
service inherits a consistent, production-ready networking layer.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from urllib.parse import urlencode

import requests

from findpapers.utils.version import package_version

logger = logging.getLogger(__name__)

_REPO_URL = "https://github.com/jonatasgrosman/findpapers"

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

    A :class:`requests.Session` is created lazily on the first HTTP call
    so that TCP+TLS connections are pooled and reused across requests to
    the same host.

    Subclasses must implement :attr:`name` and :attr:`min_request_interval`.
    """

    # Shared rate-limiter state; assignment in _rate_limit creates an instance
    # attribute that shadows this default, so multiple instances are isolated.
    _last_request_time: float = 0.0

    # Default HTTP timeout in seconds for all requests.  Subclasses or callers
    # can override by setting ``self._timeout`` in ``__init__``.
    _timeout: float = 30.0

    # ------------------------------------------------------------------
    # HTTP Session (connection pooling)
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        """Return the shared :class:`requests.Session`, creating it lazily.

        Using a session allows ``urllib3`` to keep TCP+TLS connections alive
        across consecutive requests to the same host, which significantly
        reduces latency for connectors that issue many paginated calls.

        Returns
        -------
        requests.Session
            The reusable HTTP session bound to this connector instance.
        """
        # Instance attribute created on first access; avoids requiring
        # subclasses to call super().__init__().
        if not hasattr(self, "_http_session"):
            self._http_session = requests.Session()
        return self._http_session

    def close(self) -> None:
        """Close the underlying HTTP session, releasing pooled connections.

        Safe to call multiple times or even if no request was ever made.
        """
        if hasattr(self, "_http_session"):
            self._http_session.close()
            del self._http_session

    # Context-manager protocol so connectors can be used with ``with``.

    def __enter__(self) -> ConnectorBase:
        """Enter the runtime context and return the connector itself.

        Returns
        -------
        ConnectorBase
            ``self``, allowing ``with Connector() as c: ...`` usage.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        """Exit the runtime context, closing the HTTP session."""
        self.close()

    def __del__(self) -> None:
        """Best-effort cleanup: close the session when garbage-collected.

        This is a safety-net only; callers should prefer :meth:`close` or
        a ``with`` block for deterministic resource release.
        """
        self.close()

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

    def _library_user_agent(self) -> str:
        """Build the library's standard ``User-Agent`` string.

        Format: ``findpapers/<version> (<repo_url>; mailto:<email>)`` when an
        email is available, or ``findpapers/<version> (<repo_url>)`` otherwise.
        Several academic APIs (CrossRef, OpenAlex) grant higher rate-limits
        when a ``mailto:`` clause is present.

        Returns
        -------
        str
            User-Agent header value.
        """
        version = package_version()
        email: str | None = getattr(self, "_email", None)
        if email:
            return f"findpapers/{version} ({_REPO_URL}; mailto:{email})"
        return f"findpapers/{version} ({_REPO_URL})"

    def _prepare_headers(self, headers: dict) -> dict:
        """Inject the library ``User-Agent`` and return augmented headers.

        Subclasses should call ``super()._prepare_headers(headers)`` and then
        add their own keys (API tokens, Accept types, etc.).

        Parameters
        ----------
        headers : dict
            Raw HTTP headers supplied by the caller.

        Returns
        -------
        dict
            Headers with ``User-Agent`` set (caller values take precedence).
        """
        return {"User-Agent": self._library_user_agent(), **headers}

    def _get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
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
        response = self._get_session().get(
            url,
            params=prepared_params or None,
            headers=prepared_headers or None,
            timeout=self._timeout,
        )
        self._last_request_time = time.monotonic()
        self._log_response(response)
        response.raise_for_status()
        return response

    def _post(
        self,
        url: str,
        json_body: dict | list | None = None,
        params: dict | None = None,
        headers: dict | None = None,
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
        response = self._get_session().post(
            url,
            json=json_body,
            params=prepared_params or None,
            headers=prepared_headers or None,
            timeout=self._timeout,
        )
        self._last_request_time = time.monotonic()
        self._log_response(response)
        response.raise_for_status()
        return response

    def _log_request(
        self,
        url: str,
        params: dict | None = None,
        method: str = "GET",
        headers: dict | None = None,
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

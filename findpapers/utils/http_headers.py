"""HTTP browser-header utilities.

Provides a pool of realistic browser User-Agent strings and a helper that
returns a randomised but consistent set of HTTP headers for each call.

Rotating between different User-Agents helps avoid per-IP rate-limit and
bot-detection responses (HTTP 418 / 403) that some academic publishers return
when they detect the default ``python-requests/x.y`` agent.
"""

from __future__ import annotations

import random as _random_module
from random import Random

# ---------------------------------------------------------------------------
# User-Agent pool
# ---------------------------------------------------------------------------
# Covers major platforms and recent Chrome / Firefox / Safari / Edge versions
# to maximise compatibility with bot-detection heuristics used by academic
# publishers (IEEE, Elsevier, Springer, ACM, Wiley, …).
#
# NOTE: These version strings should be refreshed periodically (e.g. once or
# twice a year) so they stay within the range of versions that publishers
# consider "current".  Outdated versions may trigger stricter bot detection.
_USER_AGENTS: list[str] = [
    # Chrome on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    # Chrome on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.6099.130 Safari/537.36"
    ),
    # Chrome on Linux
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox on macOS
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:124.0) Gecko/20100101 Firefox/124.0"),
    # Firefox on Linux
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Safari on macOS
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.2 Safari/605.1.15"
    ),
    # Edge on Windows
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0"
    ),
]

# ---------------------------------------------------------------------------
# Sec-Fetch headers (Fetch Metadata Request Headers — RFC 8941 / W3C spec)
# ---------------------------------------------------------------------------
# Modern browsers always include these when navigating directly to a URL
# (e.g. typing it in the address bar).  Their *absence* is an extremely
# reliable bot indicator used by WAFs at Wiley, OUP, ACM, bioRxiv, eLife,
# MDPI and many others.
#
# Values simulate top-level navigation ("user clicked a link" / "typed URL"):
#   Sec-Fetch-Site: none   — no referring site (direct navigation)
#   Sec-Fetch-Mode: navigate — standard page load
#   Sec-Fetch-Dest: document — fetching an HTML document
#   Sec-Fetch-User: ?1     — triggered by a user gesture
_SEC_FETCH_HEADERS: dict[str, str] = {
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-User": "?1",
    # Cache-Control mirrors what Chrome sends on hard-navigation (Ctrl+Shift+R
    # sends max-age=0; normal navigation sends no-cache for first load).
    "Cache-Control": "max-age=0",
}

# ---------------------------------------------------------------------------
# sec-ch-ua Client Hints (Chromium/Edge only)
# ---------------------------------------------------------------------------
# Chrome and Edge send UA Client Hints alongside the traditional User-Agent.
# Each entry maps a substring found in the User-Agent to the matching brand
# list.  Absence of these headers when the User-Agent claims Chrome/Edge is
# another bot-detection vector checked by sites like Cloudflare, Akamai, and
# publisher-specific WAFs.
#
# Format follows the Structured Headers spec (RFC 8941 sf-list):
#   "Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"
_CHROME_CLIENT_HINTS: dict[str, dict[str, str]] = {
    # Edge must come before Chrome/122 because Edge UAs contain both "Edg/" and
    # "Chrome/122" — a first-match lookup would otherwise return Chrome hints.
    "Edg/122": {
        "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Microsoft Edge";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    "Chrome/122": {
        "sec-ch-ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    "Chrome/120": {
        "sec-ch-ua": '"Chromium";v="120", "Not(A:Brand";v="8", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
}


def _client_hints_for_ua(user_agent: str) -> dict[str, str]:
    """Return ``sec-ch-ua`` Client Hint headers matching *user_agent*.

    Only Chromium-based browsers (Chrome, Edge) send Client Hints.
    Firefox and Safari do not, so no hints are returned for those agents.

    Parameters
    ----------
    user_agent : str
        The User-Agent string to match against known Chromium versions.

    Returns
    -------
    dict[str, str]
        Client Hint header dict (may be empty for non-Chromium agents).
    """
    for ua_fragment, hints in _CHROME_CLIENT_HINTS.items():
        if ua_fragment in user_agent:
            return hints
    return {}


def get_browser_headers(rng: Random | None = None) -> dict[str, str]:
    """Return a set of HTTP headers that mimic a real browser request.

    A User-Agent is picked at random from a pool covering Chrome, Firefox,
    Safari, and Edge on Windows, macOS, and Linux.  Beyond the User-Agent,
    the returned dict includes:

    * Standard navigation headers (``Accept``, ``Accept-Language``, etc.)
    * **Sec-Fetch-*** headers (Fetch Metadata, W3C spec) — their absence is a
      reliable bot indicator used by WAFs at Wiley, OUP, ACM, bioRxiv, eLife,
      MDPI and others.
    * **sec-ch-ua** Client Hints for Chromium-based agents — another
      fingerprint checked by Cloudflare and publisher-specific WAFs.

    Randomising the agent across requests reduces the risk of IP-level
    bot-detection that some academic publishers apply when they see repeated
    identical User-Agent strings.

    Parameters
    ----------
    rng : random.Random | None
        Optional :class:`random.Random` instance for reproducible selection
        (useful in tests).  When ``None``, the module-level default PRNG is
        used.

    Returns
    -------
    dict[str, str]
        Headers dict ready to be passed to ``requests.get(headers=…)``.

    Examples
    --------
    >>> headers = get_browser_headers()
    >>> "User-Agent" in headers
    True
    >>> "python-requests" not in headers["User-Agent"]
    True
    >>> "Sec-Fetch-Dest" in headers
    True
    """
    _rng: Random = rng if rng is not None else _random_module  # type: ignore[assignment]
    user_agent: str = _rng.choice(_USER_AGENTS)
    headers: dict[str, str] = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Accept-Encoding is intentionally omitted here.  httpx manages
        # content-encoding negotiation and decompression internally; if the
        # caller supplies an explicit Accept-Encoding header, httpx disables
        # auto-decompression and returns raw (e.g. Brotli) bytes, which breaks
        # HTML parsing.  requests also adds Accept-Encoding automatically.
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    headers.update(_SEC_FETCH_HEADERS)
    headers.update(_client_hints_for_ua(user_agent))
    return headers

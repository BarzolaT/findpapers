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


def get_browser_headers(rng: Random | None = None) -> dict[str, str]:
    """Return a set of HTTP headers that mimic a real browser request.

    A User-Agent is picked at random from a pool covering Chrome, Firefox,
    Safari, and Edge on Windows, macOS, and Linux.  Randomising the agent
    across requests reduces the risk of IP-level bot-detection that some
    academic publishers (IEEE, Elsevier, Springer, …) apply when they see
    repeated identical User-Agent strings.

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
    """
    _rng: Random = rng if rng is not None else _random_module  # type: ignore[assignment]
    user_agent: str = _rng.choice(_USER_AGENTS)
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

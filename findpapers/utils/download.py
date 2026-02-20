"""Web scraping and download helper utilities.

Provides pure, stateless helper functions used by :class:`DownloadRunner`
and potentially other components that need to resolve PDF URLs, build safe
filenames, or construct proxy configurations.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.parse

logger = logging.getLogger(__name__)


def resolve_pdf_url(response_url: str, doi: str | None = None) -> str | None:
    """Attempt to resolve a direct PDF URL from an HTML landing-page URL.

    Recognises publisher-specific URL patterns for a set of known academic
    publishers and transforms them into a URL that should serve the PDF
    directly.

    Parameters
    ----------
    response_url : str
        Final URL (after any redirects) that returned an HTML response.
    doi : str | None
        DOI of the paper, used when the publisher URL does not embed it.
        Defaults to ``None``.

    Returns
    -------
    str | None
        A URL expected to serve the PDF, or ``None`` when the publisher is
        not recognised.

    Examples
    --------
    >>> resolve_pdf_url("https://dl.acm.org/doi/10.1145/1234567.1234568")
    'https://dl.acm.org/doi/pdf/10.1145/1234567.1234568'
    """
    parts = urllib.parse.urlsplit(response_url)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(response_url).query)
    path = parts.path.rstrip("/").split("?")[0]
    host = f"{parts.scheme}://{parts.hostname}"

    if host == "https://dl.acm.org":
        resolved_doi = doi
        if resolved_doi is None and path.startswith("/doi/") and "/doi/pdf/" not in path:
            resolved_doi = path[5:]
        if resolved_doi is None:
            return None
        return f"https://dl.acm.org/doi/pdf/{resolved_doi}"

    if host == "https://ieeexplore.ieee.org":
        if path.startswith("/document/"):
            doc_id = path[10:]
        elif qs.get("arnumber"):
            doc_id = qs["arnumber"][0]
        else:
            return None
        return f"{host}/stamp/stamp.jsp?tp=&arnumber={doc_id}"

    if host in ("https://www.sciencedirect.com", "https://linkinghub.elsevier.com"):
        paper_id = path.split("/")[-1]
        return (
            "https://www.sciencedirect.com/science/article/pii/"
            f"{paper_id}/pdfft?isDTMRedir=true&download=true"
        )

    if host == "https://pubs.rsc.org":
        return response_url.replace("/articlelanding/", "/articlepdf/")

    if host in ("https://www.tandfonline.com", "https://www.frontiersin.org"):
        return response_url.replace("/full", "/pdf")

    if host in (
        "https://pubs.acs.org",
        "https://journals.sagepub.com",
        "https://royalsocietypublishing.org",
    ):
        return response_url.replace("/doi", "/doi/pdf")

    if host == "https://link.springer.com":
        return response_url.replace("/article/", "/content/pdf/").replace("%2F", "/") + ".pdf"

    if host == "https://www.isca-speech.org":
        return response_url.replace("/abstracts/", "/pdfs/").replace(".html", ".pdf")

    if host == "https://onlinelibrary.wiley.com":
        return response_url.replace("/full/", "/pdfdirect/").replace("/abs/", "/pdfdirect/")

    if host in ("https://www.jmir.org", "https://www.mdpi.com"):
        return f"{response_url}/pdf"

    if host == "https://www.pnas.org":
        return response_url.replace("/content/", "/content/pnas/") + ".full.pdf"

    if host == "https://www.jneurosci.org":
        return response_url.replace("/content/", "/content/jneuro/") + ".full.pdf"

    if host == "https://www.ijcai.org":
        paper_id = response_url.split("/")[-1].zfill(4)
        return "/".join(response_url.split("/")[:-1]) + "/" + paper_id + ".pdf"

    if host == "https://asmp-eurasipjournals.springeropen.com":
        return response_url.replace("/articles/", "/track/pdf/")

    return None


def build_filename(year: int | None, title: str | None) -> str:
    """Build a sanitised ``year-title.pdf`` filename for a paper.

    Non-alphanumeric characters (except ``-``) are replaced with underscores
    so the result is safe to use as a filesystem path on all major platforms.

    Parameters
    ----------
    year : int | None
        Publication year. Uses ``"unknown"`` when ``None``.
    title : str | None
        Paper title. Uses ``"paper"`` when ``None`` or empty.

    Returns
    -------
    str
        Sanitised filename ending in ``.pdf``.

    Examples
    --------
    >>> build_filename(2024, "Deep Learning: A Survey")
    'Deep Learning: A Survey'
    >>> build_filename(2024, "Deep Learning: A Survey")
    '2024-Deep_Learning__A_Survey.pdf'
    """
    safe_year = str(year) if year is not None else "unknown"
    safe_title = title if title else "paper"
    raw = f"{safe_year}-{safe_title}"
    sanitised = re.sub(r"[^\w\d-]", "_", raw)
    return f"{sanitised}.pdf"


def build_proxies(proxy: str | None = None) -> dict[str, str] | None:
    """Build a *requests*-compatible proxy mapping if a proxy is configured.

    The proxy value is taken from the *proxy* parameter first; if that is
    ``None``, the ``FINDPAPERS_PROXY`` environment variable is checked.

    Institutional proxies are almost always plain-HTTP servers.  When the
    configured URL uses ``https://``, *requests* / urllib3 would try to
    establish an SSL connection to the proxy itself — which fails with a
    ``WRONG_VERSION_NUMBER`` SSL error.  To avoid this, the scheme is
    silently normalised from ``https://`` to ``http://``.

    Parameters
    ----------
    proxy : str | None
        Explicit proxy URL.  When ``None``, falls back to the environment
        variable ``FINDPAPERS_PROXY``.

    Returns
    -------
    dict[str, str] | None
        Mapping suitable for the ``proxies`` keyword of ``requests.get``,
        or ``None`` when no proxy is configured.

    Examples
    --------
    >>> build_proxies("http://proxy.example.com:8080")
    {'http': 'http://proxy.example.com:8080', 'https': 'http://proxy.example.com:8080'}
    >>> build_proxies("https://proxy.example.com:8080")
    {'http': 'http://proxy.example.com:8080', 'https': 'http://proxy.example.com:8080'}
    """
    resolved = proxy or os.getenv("FINDPAPERS_PROXY")
    if not resolved:
        return None
    if resolved.startswith("https://"):
        normalized = "http://" + resolved[len("https://") :]
        logger.warning(
            "Proxy URL uses 'https://' scheme ('%s'), but institutional proxies "
            "typically speak plain HTTP.  Normalising to 'http://' to avoid SSL "
            "handshake failures (WRONG_VERSION_NUMBER).  If your proxy genuinely "
            "requires HTTPS, this normalisation will break the connection — in that "
            "case please report an issue.",
            resolved,
        )
        resolved = normalized
    return {"http": resolved, "https": resolved}

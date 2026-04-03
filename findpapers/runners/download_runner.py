"""DownloadRunner: downloads PDFs for a list of papers."""

from __future__ import annotations

import datetime
import logging
import os
import re
import urllib.parse
from datetime import UTC
from time import perf_counter
from typing import cast

import lxml.etree as _lxml_etree
import lxml.html as _lxml_html
from curl_cffi.requests import Response as _CurlResponse
from curl_cffi.requests import Session as _CurlSession
from curl_cffi.requests.errors import RequestsError as _CurlError

from findpapers.core.paper import Paper
from findpapers.utils.logging_config import configure_verbose_logging
from findpapers.utils.parallel import execute_tasks

logger = logging.getLogger(__name__)


class DownloadRunner:
    """Runner that downloads PDFs for a provided list of papers.

    For each paper, the runner tries all known URLs and follows HTML landing
    pages to resolve the actual PDF URL.  Downloaded files are saved to
    *output_directory* with a ``year-title.pdf`` naming scheme.  Both
    successful and failed downloads are logged to ``download_log.txt``
    inside *output_directory*.

    Parameters
    ----------
    papers : list[Paper]
        Papers to download.
    output_directory : str
        Directory where PDFs and the error log will be written.
    num_workers : int
        Number of parallel workers.  Defaults to ``1``, which runs
        sequentially.  Values greater than ``1`` enable parallel execution.
    timeout : float | None
        Per-request HTTP timeout in seconds.
    proxy : str | None
        Proxy URL for HTTP/HTTPS requests (also read from
        ``FINDPAPERS_PROXY`` env variable if ``None``).
    ssl_verify : bool
        Whether to verify SSL certificates.  Set to ``False`` when using
        institutional proxies that perform SSL inspection.  Defaults to
        ``True``.

    Examples
    --------
    >>> runner = DownloadRunner(papers=papers, output_directory="/tmp/pdfs")
    >>> metrics = runner.run(verbose=True)
    """

    def __init__(
        self,
        papers: list[Paper],
        output_directory: str,
        num_workers: int = 1,
        timeout: float | None = 10.0,
        proxy: str | None = None,
        ssl_verify: bool = True,
    ) -> None:
        """Initialise download configuration without executing it."""
        self._results = list(papers)
        self._metrics: dict[str, int | float] = {}
        self._output_directory = output_directory
        self._num_workers = num_workers
        self._timeout = timeout
        self._proxy = proxy
        self._ssl_verify = ssl_verify

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, verbose: bool = False, show_progress: bool = True) -> dict[str, int | float]:
        """Download PDFs for all configured papers.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.
        show_progress : bool
            When ``True`` (default), display a tqdm progress bar while
            papers are being downloaded.  Set to ``False`` to suppress
            progress output (e.g. in non-interactive environments or to
            keep log output clean).

        Returns
        -------
        dict[str, int | float]
            Metrics with at least ``total_papers``, ``downloaded_papers``,
            and ``runtime_in_seconds``.
        """
        _root_logger = logging.getLogger()
        _saved_log_level = _root_logger.level
        if verbose:
            configure_verbose_logging()
            logger.info("=== DownloadRunner Configuration ===")
            logger.info("Total papers: %d", len(self._results))
            logger.info("Output directory: %s", self._output_directory)
            logger.info("Num workers: %d", self._num_workers)
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("Proxy: %s", self._mask_proxy_credentials(self._proxy))
            logger.info("SSL verify: %s", self._ssl_verify)
            logger.info("====================================")

        start = perf_counter()
        self._results = list(self._results)
        metrics: dict[str, int | float] = {
            "total_papers": len(self._results),
            "runtime_in_seconds": 0.0,
            "downloaded_papers": 0,
        }

        os.makedirs(self._output_directory, exist_ok=True)
        log_path = os.path.join(self._output_directory, "download_log.txt")
        with open(log_path, "a", encoding="utf-8") as fp:
            now = datetime.datetime.now(UTC)
            ts = datetime.datetime.strftime(now, "%Y-%m-%d %H:%M:%S")
            separator = "=" * 80
            fp.write(f"\n{separator}\nDownload session started: {ts}\n{separator}\n")

        num_workers = self._num_workers
        timeout = self._timeout
        proxies = self._build_proxies(self._proxy)
        ssl_verify = self._ssl_verify

        def _download_task(paper: Paper) -> tuple[bool, list[str]]:
            return self._download_paper(
                paper,
                self._output_directory,
                timeout=timeout,
                proxies=proxies,
                ssl_verify=ssl_verify,
            )

        for paper, result, error in execute_tasks(
            self._results,
            _download_task,
            num_workers=num_workers,
            timeout=None,
            progress_total=len(self._results),
            progress_unit="paper",
            progress_desc="Downloading",
            use_progress=show_progress,
        ):
            if error is not None or result is None:
                self._log_download_error(log_path, paper.title, [])
                if verbose:
                    logger.warning("Error downloading '%s': %s", paper.title, error)
                continue
            downloaded, attempted_urls = result
            if downloaded:
                metrics["downloaded_papers"] += 1
                self._log_download_success(log_path, paper.title, attempted_urls)
            else:
                self._log_download_error(log_path, paper.title, attempted_urls)

        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics

        if verbose:
            logger.info("=== Download Summary ===")
            logger.info("Total papers: %d", int(metrics["total_papers"]))
            logger.info("Downloaded: %d", int(metrics["downloaded_papers"]))
            failed = int(metrics["total_papers"] - metrics["downloaded_papers"])
            logger.info("Failed: %d", failed)
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            logger.info("========================")

        _root_logger.setLevel(_saved_log_level)
        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _log_response(self, response: _CurlResponse) -> None:
        """Log a concise summary of an HTTP response at DEBUG level.

        This mirrors the behaviour in SearchConnectorBase._log_response but is
        local to the runner so downloads always produce a consistent
        debug message.
        """
        if not logger.isEnabledFor(logging.DEBUG):
            return
        status = f"{response.status_code} {getattr(response, 'reason', '')}"
        content_type = response.headers.get("content-type", "unknown").split(";")[0].strip()
        size = len(getattr(response, "content", b""))
        logger.debug(
            "[DownloadRunner] <- %s | content-type: %s | %d bytes", status, content_type, size
        )

    @staticmethod
    def _mask_proxy_credentials(proxy: str | None) -> str:
        """Return a redacted proxy URL safe for logging.

        Credentials embedded in the URL (``user:password@``) are replaced
        with ``***:***`` so that secrets are never written to log output.

        Parameters
        ----------
        proxy : str | None
            Raw proxy URL, potentially containing embedded credentials.

        Returns
        -------
        str
            Proxy representation with credentials masked, or ``"none"``
            when *proxy* is ``None``.
        """
        if not proxy:
            return "none"
        try:
            parsed = urllib.parse.urlparse(proxy)
            if parsed.username or parsed.password:
                masked_netloc = f"***:***@{parsed.hostname or ''}"
                if parsed.port:
                    masked_netloc += f":{parsed.port}"
                return urllib.parse.urlunparse(parsed._replace(netloc=masked_netloc))
        except (ValueError, AttributeError):
            pass
        return proxy

    @staticmethod
    def _extract_meta_pdf_url(html_content: bytes, base_url: str = "") -> str | None:
        """Extract a direct PDF URL from HTML meta tags.

        Checks the following meta tag names (in order of preference):
        ``citation_pdf_url`` and ``fulltext_pdf_url``.

        Relative URLs are resolved against *base_url* so the returned value
        is always an absolute URL (or ``None``).

        Parameters
        ----------
        html_content : bytes
            Raw HTML response body.
        base_url : str
            Absolute URL of the page, used to resolve relative meta-tag values.
            Defaults to ``""`` (no resolution performed).

        Returns
        -------
        str | None
            The absolute PDF URL found in a meta tag, or ``None`` when not present.
        """
        try:
            tree = _lxml_html.fromstring(html_content)
        except Exception:
            return None
        # Attribute values are case-insensitive per HTML spec; lxml lower-cases them.
        _meta_names = {"citation_pdf_url", "fulltext_pdf_url"}
        for meta in cast(list[_lxml_etree._Element], tree.xpath("//head/meta")):
            name = (meta.get("name") or meta.get("property") or "").lower()
            if name in _meta_names:
                content = meta.get("content", "").strip()
                if content:
                    # Resolve relative paths (e.g. /en/download/…) to absolute URLs.
                    return urllib.parse.urljoin(base_url, content) if base_url else content
        return None

    @staticmethod
    def _resolve_pdf_url(response_url: str, doi: str | None = None) -> str | None:
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
        >>> DownloadRunner._resolve_pdf_url("https://dl.acm.org/doi/10.1145/1234567.1234568")
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
            # stamp.jsp is an HTML frame-loader; the actual PDF is served by
            # stampPDF/getPDF.jsp with the same arnumber parameter.
            if path.startswith("/stamp/"):
                arnumber = qs.get("arnumber", [None])[0]
                if arnumber is None:
                    return None
                return f"{host}/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}&ref="
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
            # Guard against double-insertion when the URL already contains /doi/pdf/.
            if "/doi/pdf/" in path:
                return None
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

    @staticmethod
    def _build_filename(year: int | None, title: str | None) -> str:
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
        >>> DownloadRunner._build_filename(2024, "Deep Learning: A Survey")
        '2024-Deep_Learning__A_Survey.pdf'
        """
        safe_year = str(year) if year is not None else "unknown"
        safe_title = title if title else "paper"
        raw = f"{safe_year}-{safe_title}"
        sanitised = re.sub(r"[^\w-]", "_", raw)
        return f"{sanitised}.pdf"

    @staticmethod
    def _build_proxies(proxy: str | None = None) -> dict[str, str] | None:
        """Build a *requests*-compatible proxy mapping if a proxy is configured.

        The proxy value is taken from the *proxy* parameter first; if that is
        ``None``, the ``FINDPAPERS_PROXY`` environment variable is checked.

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
        >>> DownloadRunner._build_proxies("http://proxy.example.com:8080")
        {'http': 'http://proxy.example.com:8080', 'https': 'http://proxy.example.com:8080'}
        """
        resolved = proxy or os.getenv("FINDPAPERS_PROXY")
        if not resolved:
            return None
        return {"http": resolved, "https": resolved}

    def _log_download_success(
        self,
        log_path: str,
        title: str,
        attempted_urls: list[str],
    ) -> None:
        """Append a success entry to the download log file.

        Parameters
        ----------
        log_path : str
            Path to the download log file.
        title : str
            Paper title.
        attempted_urls : list[str]
            URLs that were tried.

        Returns
        -------
        None
        """
        with open(log_path, "a", encoding="utf-8") as fp:
            fp.write(f"\n[OK] {title}\n")
            if not attempted_urls:
                fp.write("  -> (already downloaded, skipped)\n")
            else:
                for url in attempted_urls:
                    fp.write(f"  -> {url}\n")

    def _log_download_error(
        self,
        log_path: str,
        title: str,
        attempted_urls: list[str],
    ) -> None:
        """Append a failure entry to the download log file.

        Parameters
        ----------
        log_path : str
            Path to the download log file.
        title : str
            Paper title.
        attempted_urls : list[str]
            URLs that were tried.

        Returns
        -------
        None
        """
        with open(log_path, "a", encoding="utf-8") as fp:
            fp.write(f"\n[FAILED] {title}\n")
            if not attempted_urls:
                fp.write("  -> (no URLs available)\n")
            else:
                for url in attempted_urls:
                    fp.write(f"  -> {url}\n")

    def _download_paper(
        self,
        paper: Paper,
        output_directory: str,
        timeout: float | None,
        proxies: dict[str, str] | None,
        ssl_verify: bool = True,
    ) -> tuple[bool, list[str]]:
        """Attempt to download the PDF for a single paper.

        Parameters
        ----------
        paper : Paper
            Paper to download.
        output_directory : str
            Target directory.
        timeout : float | None
            HTTP request timeout.
        proxies : dict[str, str] | None
            Proxy configuration.
        ssl_verify : bool
            Whether to verify SSL certificates.

        Returns
        -------
        tuple[bool, list[str]]
            ``(downloaded, attempted_urls)`` where *downloaded* is ``True``
            when the PDF was saved successfully.
        """
        attempted_urls: list[str] = []
        year = getattr(paper.publication_date, "year", None) if paper.publication_date else None
        output_filepath = os.path.join(output_directory, self._build_filename(year, paper.title))
        if os.path.exists(output_filepath):
            logger.info("PDF already exists, skipping: %s", output_filepath)
            return True, attempted_urls

        # Build ordered candidate URL list: pdf_url first, then url, then DOI
        # so the most likely direct PDF source is tried before HTML landing pages.
        candidate_urls: list[str] = []
        seen: set[str] = set()  # guards pre-request candidate dedup
        visited: set[str] = set()  # guards post-redirect final-URL dedup

        def _add(u: str | None) -> None:
            # Skip relative URLs — they cannot be requested and indicate bad data
            # from a connector (e.g. pdf_url stored as "/en/download/…").
            if u and u.startswith(("http://", "https://")) and u not in seen:
                candidate_urls.append(u)
                seen.add(u)

        _add(paper.pdf_url)
        _add(paper.url)
        if paper.doi is not None:
            _add(f"https://doi.org/{paper.doi}")

        for url in candidate_urls:
            try:
                response = self._request(
                    url, timeout=timeout, proxies=proxies, ssl_verify=ssl_verify
                )
                if response is None:
                    # Log the original URL when no response was received.
                    attempted_urls.append(url)
                    logger.debug("No response for %s", url)
                    continue
                # Use the final URL after redirects so the log reflects where
                # the request actually landed (e.g. DOI → publisher landing page).
                # Skip entirely if this final URL was already visited via a
                # different candidate (e.g. paper.url and doi both redirect here).
                if response.url in visited:
                    logger.debug("Skipping already-visited URL: %s", response.url)
                    continue
                visited.add(response.url)
                attempted_urls.append(response.url)
                # Log response summary here as well so that callers running
                # in different execution contexts (threads) always see the
                # response regardless of _request internals.
                self._log_response(response)
                content_type = response.headers.get("content-type", "").lower()

                if "text/html" in content_type:
                    # Build a prioritised list of PDF URL candidates from the landing page:
                    # 1. Meta tag (publisher-agnostic, preferred when available).
                    # 2. Known publisher URL pattern as fallback.
                    # Both are tried in order; the first that returns a PDF wins.
                    html_pdf_candidates: list[str] = []
                    meta_pdf = self._extract_meta_pdf_url(response.content, base_url=response.url)
                    if meta_pdf:
                        html_pdf_candidates.append(meta_pdf)
                    pattern_pdf = self._resolve_pdf_url(response.url, doi=paper.doi)
                    if pattern_pdf and pattern_pdf not in html_pdf_candidates:
                        html_pdf_candidates.append(pattern_pdf)

                    for pdf_candidate in html_pdf_candidates:
                        if pdf_candidate in visited:
                            continue
                        visited.add(pdf_candidate)
                        attempted_urls.append(pdf_candidate)
                        pdf_response = self._request(
                            pdf_candidate, timeout=timeout, proxies=proxies, ssl_verify=ssl_verify
                        )
                        if pdf_response is None:
                            logger.debug("No response for %s", pdf_candidate)
                            continue
                        self._log_response(pdf_response)
                        if (
                            "application/pdf"
                            in pdf_response.headers.get("content-type", "").lower()
                        ):
                            with open(output_filepath, "wb") as fp:
                                fp.write(pdf_response.content)
                            return True, attempted_urls
                    # None of the landing-page candidates yielded a PDF;
                    # move on to the next main URL candidate.
                    continue

                if "application/pdf" in content_type:
                    with open(output_filepath, "wb") as fp:
                        fp.write(response.content)
                    return True, attempted_urls
            except OSError:
                attempted_urls.append(url)
                logger.debug("Download attempt failed", exc_info=True)

        return False, attempted_urls

    def _request(
        self,
        url: str,
        timeout: float | None,
        proxies: dict[str, str] | None,
        ssl_verify: bool = True,
    ) -> _CurlResponse | None:
        """Perform a GET request, returning ``None`` on failure.

        Parameters
        ----------
        url : str
            URL to fetch.
        timeout : float | None
            Request timeout in seconds.
        proxies : dict[str, str] | None
            Proxy configuration.
        ssl_verify : bool
            Whether to verify SSL certificates.  Set to ``False`` when using
            proxies that perform SSL inspection.

        Returns
        -------
        _CurlResponse | None
            Response object, or ``None`` when the request fails.
        """
        try:
            logger.debug("GET %s", url)
            with _CurlSession(impersonate="chrome") as session:
                response = session.get(
                    url,
                    proxies=proxies,
                    verify=ssl_verify,
                    allow_redirects=True,
                    timeout=timeout,
                )
        except _CurlError:
            logger.debug("Request failed for %s", url, exc_info=True)
            return None
        content_type = response.headers.get("content-type", "unknown").split(";")[0].strip()
        logger.debug(
            "<- %s %s | content-type: %s | %d bytes",
            response.status_code,
            response.reason,
            content_type,
            len(response.content),
        )
        if response.status_code == 418:
            logger.warning(
                "Server returned 418 (bot-detection) for %s — "
                "the publisher is blocking automated requests.",
                url,
            )
        elif not response.ok:
            logger.debug(
                "Non-success status %s for %s",
                response.status_code,
                url,
            )
        return response  # type: ignore[no-any-return]

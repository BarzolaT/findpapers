"""DownloadRunner: downloads PDFs for a list of papers."""

from __future__ import annotations

import datetime
import logging
import os
import urllib.parse
from time import perf_counter

import requests

from findpapers.core.paper import Paper
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.utils.download import build_filename, build_proxies, resolve_pdf_url
from findpapers.utils.http_headers import get_browser_headers
from findpapers.utils.parallel import execute_tasks

logger = logging.getLogger(__name__)


class DownloadRunner:
    """Runner that downloads PDFs for a provided list of papers.

    For each paper, the runner tries all known URLs and follows HTML landing
    pages to resolve the actual PDF URL.  Downloaded files are saved to
    *output_directory* with a ``year-title.pdf`` naming scheme.  Failures are
    appended to ``download_errors.txt`` inside *output_directory*.

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
    >>> runner.run(verbose=True)
    >>> metrics = runner.get_metrics()
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
        self._executed = False
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

    def run(self, verbose: bool = False) -> None:
        """Download PDFs for all configured papers.

        Parameters
        ----------
        verbose : bool
            Enable verbose logging and print a summary after execution.

        Returns
        -------
        None
        """
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
            # Suppress verbose output from third-party HTTP libraries so that
            # only findpapers' own loggers emit debug messages.
            for _noisy in ("urllib3", "requests", "httpx", "charset_normalizer"):
                logging.getLogger(_noisy).setLevel(logging.WARNING)
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
        error_log_path = os.path.join(self._output_directory, "download_errors.txt")
        with open(error_log_path, "a", encoding="utf-8") as fp:
            now = datetime.datetime.now()
            fp.write(
                "------- A new download process started at: "
                f"{datetime.datetime.strftime(now, '%Y-%m-%d %H:%M:%S')} \n"
            )

        num_workers = self._num_workers
        timeout = self._timeout
        proxies = self._build_proxies()
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
            use_progress=True,
        ):
            if error is not None or result is None:
                self._log_download_error(error_log_path, paper.title, [])
                if verbose:
                    logger.warning("Error downloading '%s': %s", paper.title, error)
                continue
            downloaded, attempted_urls = result
            if downloaded:
                metrics["downloaded_papers"] += 1
            else:
                self._log_download_error(error_log_path, paper.title, attempted_urls)

        metrics["runtime_in_seconds"] = perf_counter() - start
        self._metrics = metrics
        self._executed = True

        if verbose:
            logger.info("=== Download Summary ===")
            logger.info("Total papers: %d", int(metrics["total_papers"]))
            logger.info("Downloaded: %d", int(metrics["downloaded_papers"]))
            failed = int(metrics["total_papers"] - metrics["downloaded_papers"])
            logger.info("Failed: %d", failed)
            logger.info("Runtime: %.2f s", metrics["runtime_in_seconds"])
            logger.info("========================")

    def get_metrics(self) -> dict[str, int | float]:
        """Return a snapshot of numeric performance metrics.

        Returns
        -------
        dict[str, int | float]
            Metrics with at least ``total_papers``, ``downloaded_papers``, and
            ``runtime_in_seconds``.

        Raises
        ------
        SearchRunnerNotExecutedError
            If :meth:`run` has not been called yet.
        """
        self._ensure_executed()
        return dict(self._metrics)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_executed(self) -> None:
        """Raise if :meth:`run` has not been called.

        Raises
        ------
        SearchRunnerNotExecutedError
            When the runner has not been executed.
        """
        if not self._executed:
            raise SearchRunnerNotExecutedError("DownloadRunner has not been executed yet.")

    def _build_proxies(self) -> dict[str, str] | None:
        """Build a proxies dict for *requests* if a proxy is configured.

        Returns
        -------
        dict[str, str] | None
            Proxies mapping, or ``None``.
        """
        return build_proxies(self._proxy)

    def _log_response(self, response: requests.Response) -> None:
        """Log a concise summary of an HTTP response at DEBUG level.

        This mirrors the behaviour in SearcherBase._log_response but is
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
        except Exception:  # noqa: BLE001
            pass
        return proxy

    def _log_download_error(
        self,
        error_log_path: str,
        title: str,
        attempted_urls: list[str],
    ) -> None:
        """Append a failure entry to the error log file.

        Parameters
        ----------
        error_log_path : str
            Path to the error log file.
        title : str
            Paper title.
        attempted_urls : list[str]
            URLs that were tried.

        Returns
        -------
        None
        """
        with open(error_log_path, "a", encoding="utf-8") as fp:
            fp.write(f"[FAILED] {title}\n")
            if not attempted_urls:
                fp.write("Empty URL list\n")
            else:
                for url in attempted_urls:
                    fp.write(f"{url}\n")

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
        output_filepath = os.path.join(output_directory, self._build_filename(paper))
        if os.path.exists(output_filepath):
            logger.info("PDF already exists, skipping: %s", output_filepath)
            return True, attempted_urls

        # Build ordered candidate URL list: pdf_url first, then url, then DOI
        # so the most likely direct PDF source is tried before HTML landing pages.
        candidate_urls: list[str] = []
        seen: set[str] = set()

        def _add(u: str | None) -> None:
            if u and u not in seen:
                candidate_urls.append(u)
                seen.add(u)

        _add(paper.pdf_url)
        _add(paper.url)
        if paper.doi is not None:
            _add(f"http://doi.org/{paper.doi}")

        for url in candidate_urls:
            attempted_urls.append(url)
            try:
                response = self._request(
                    url, timeout=timeout, proxies=proxies, ssl_verify=ssl_verify
                )
                if response is None:
                    logger.debug("No response for %s", url)
                    continue
                # Log response summary here as well so that callers running
                # in different execution contexts (threads) always see the
                # response regardless of _request internals.
                self._log_response(response)
                content_type = response.headers.get("content-type", "").lower()

                if "text/html" in content_type:
                    pdf_url = self._resolve_pdf_url(response.url, paper)
                    if pdf_url is not None:
                        attempted_urls.append(pdf_url)
                        response = self._request(
                            pdf_url, timeout=timeout, proxies=proxies, ssl_verify=ssl_verify
                        )
                        if response is None:
                            logger.debug("No response for %s", pdf_url)
                            continue
                        self._log_response(response)
                        content_type = response.headers.get("content-type", "").lower()

                if "application/pdf" in content_type:
                    with open(output_filepath, "wb") as fp:
                        fp.write(response.content)
                    return True, attempted_urls
            except Exception:  # noqa: BLE001
                logger.debug("Download attempt failed", exc_info=True)

        return False, attempted_urls

    def _request(
        self,
        url: str,
        timeout: float | None,
        proxies: dict[str, str] | None,
        ssl_verify: bool = True,
    ) -> requests.Response | None:
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
        requests.Response | None
            Response object, or ``None`` when the request fails.
        """
        try:
            logger.debug("GET %s", url)
            response = requests.get(
                url,
                headers=get_browser_headers(),
                timeout=timeout,
                proxies=proxies,
                verify=ssl_verify,
            )
        except Exception:  # noqa: BLE001
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
        if response.status_code == 418:  # noqa: PLR2004
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
        return response

    def _build_filename(self, paper: Paper) -> str:
        """Build a sanitised filename for the paper PDF.

        Parameters
        ----------
        paper : Paper
            Paper to name.

        Returns
        -------
        str
            Sanitised ``year-title.pdf`` filename.
        """
        year = getattr(paper.publication_date, "year", None) if paper.publication_date else None
        return build_filename(year, paper.title)

    def _resolve_pdf_url(self, response_url: str, paper: Paper) -> str | None:
        """Resolve a PDF URL from an HTML landing-page URL.

        Delegates to :func:`findpapers.utils.download.resolve_pdf_url`.

        Parameters
        ----------
        response_url : str
            Final URL after any redirects.
        paper : Paper
            Paper being downloaded (used for DOI when available).

        Returns
        -------
        str | None
            Resolved PDF URL, or ``None`` for unknown publishers.
        """
        return resolve_pdf_url(response_url, doi=paper.doi)

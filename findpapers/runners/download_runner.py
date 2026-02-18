"""DownloadRunner: downloads PDFs for a list of papers."""

from __future__ import annotations

import datetime
import logging
import os
import re
import urllib.parse
from time import perf_counter

import requests

from findpapers.core.paper import Paper
from findpapers.exceptions import SearchRunnerNotExecutedError
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
    max_workers : int | None
        Maximum parallel workers. ``None`` runs sequentially.
    timeout : float | None
        Per-request and global timeout in seconds.
    proxy : str | None
        Proxy URL for HTTP/HTTPS requests (also read from
        ``FINDPAPERS_PROXY`` env variable if ``None``).

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
        max_workers: int | None = None,
        timeout: float | None = 10.0,
        proxy: str | None = None,
    ) -> None:
        """Initialise download configuration without executing it."""
        self._executed = False
        self._results = list(papers)
        self._metrics: dict[str, int | float] = {}
        self._output_directory = output_directory
        self._max_workers = max_workers
        self._timeout = timeout
        self._proxy = proxy

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
            logging.getLogger().setLevel(logging.INFO)
            logger.info("=== DownloadRunner Configuration ===")
            logger.info("Total papers: %d", len(self._results))
            logger.info("Output directory: %s", self._output_directory)
            logger.info("Max workers: %s", self._max_workers or "sequential")
            logger.info("Timeout: %s", self._timeout or "default")
            logger.info("Proxy: %s", self._proxy or "none")
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

        max_workers = self._max_workers if isinstance(self._max_workers, int) else None
        timeout = self._timeout
        proxies = self._build_proxies()

        def _download_task(paper: Paper) -> tuple[bool, list[str]]:
            return self._download_paper(
                paper,
                self._output_directory,
                timeout=timeout,
                proxies=proxies,
            )

        for paper, result, error in execute_tasks(
            self._results,
            _download_task,
            max_workers=max_workers,
            timeout=timeout,
            progress_total=len(self._results),
            progress_unit="paper",
            use_progress=True,
            stop_on_timeout=True,
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
        proxy = self._proxy or os.getenv("FINDPAPERS_PROXY")
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

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
                logger.info("Fetching: %s", url)
                response = self._request(url, timeout=timeout, proxies=proxies)
                if response is None:
                    continue
                content_type = response.headers.get("content-type", "").lower()

                if "text/html" in content_type:
                    pdf_url = self._resolve_pdf_url(response.url, paper)
                    if pdf_url is not None:
                        attempted_urls.append(pdf_url)
                        response = self._request(pdf_url, timeout=timeout, proxies=proxies)
                        if response is None:
                            continue
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

        Returns
        -------
        requests.Response | None
            Response object, or ``None`` when the request fails.
        """
        try:
            return requests.get(url, timeout=timeout, proxies=proxies)
        except Exception:  # noqa: BLE001
            return None

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
        year = self._paper_year(paper) or "unknown"
        title = paper.title or "paper"
        filename = re.sub(r"[^\w\d-]", "_", f"{year}-{title}")
        return f"{filename}.pdf"

    def _paper_year(self, paper: Paper) -> int | None:
        """Extract the publication year from a paper.

        Parameters
        ----------
        paper : Paper
            Paper to inspect.

        Returns
        -------
        int | None
            Year if available.
        """
        if paper.publication_date is None:
            return None
        return getattr(paper.publication_date, "year", None)

    def _resolve_pdf_url(self, response_url: str, paper: Paper) -> str | None:
        """Resolve a PDF URL from an HTML landing-page URL.

        Recognises publisher-specific URL patterns for a set of known
        academic publishers.

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
        parts = urllib.parse.urlsplit(response_url)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(response_url).query)
        path = parts.path.rstrip("/").split("?")[0]
        host = f"{parts.scheme}://{parts.hostname}"

        if host == "https://dl.acm.org":
            doi = paper.doi
            if doi is None and path.startswith("/doi/") and "/doi/pdf/" not in path:
                doi = path[4:]
            if doi is None:
                return None
            return f"https://dl.acm.org/doi/pdf/{doi}"

        if host == "https://ieeexplore.ieee.org":
            if path.startswith("/document/"):
                doc_id = path[10:]
            elif qs.get("arnumber"):
                doc_id = qs["arnumber"][0]
            else:
                return None
            return f"{host}/stampPDF/getPDF.jsp?tp=&arnumber={doc_id}"

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

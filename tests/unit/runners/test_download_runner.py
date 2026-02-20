"""Unit tests for DownloadRunner."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest

from findpapers.core.paper import Paper
from findpapers.core.publication import Publication
from findpapers.exceptions import SearchRunnerNotExecutedError
from findpapers.runners.download_runner import DownloadRunner


def _make_paper(
    title: str = "Test Paper",
    doi: str | None = "10.1234/test",
    urls: set[str] | None = None,
) -> Paper:
    """Create a minimal Paper for testing."""
    url = next(iter(urls)) if urls else "http://example.com/paper"
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=["Author One"],
        publication=Publication(title="Test Journal"),
        publication_date=date(2023, 1, 1),
        url=url,
        doi=doi,
    )


class TestDownloadRunnerInit:
    """Tests for DownloadRunner initialisation."""

    def test_init_stores_config(self):
        """Constructor stores configuration without executing."""
        papers = [_make_paper()]
        runner = DownloadRunner(papers=papers, output_directory="/tmp/out")
        assert runner._output_directory == "/tmp/out"  # noqa: SLF001
        assert runner._executed is False  # noqa: SLF001

    def test_get_metrics_before_run_raises(self):
        """get_metrics() before run() raises SearchRunnerNotExecutedError."""
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        with pytest.raises(SearchRunnerNotExecutedError):
            runner.get_metrics()


class TestDownloadRunnerBuildFilename:
    """Tests for _build_filename helper."""

    def test_filename_includes_year_and_title(self):
        """Filename starts with year and contains sanitised title."""
        paper = _make_paper(title="My Test Paper")
        paper.publication_date = date(2023, 5, 1)  # type: ignore[assignment]
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)  # noqa: SLF001
        assert filename.startswith("2023")
        assert filename.endswith(".pdf")

    def test_filename_sanitises_spaces(self):
        """Spaces in title are replaced with underscores."""
        paper = _make_paper(title="Hello World")
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)  # noqa: SLF001
        assert " " not in filename

    def test_filename_unknown_year_when_no_date(self):
        """Papers without publication_date use 'unknown' as year."""
        paper = _make_paper()
        paper.publication_date = None  # type: ignore[assignment]
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)  # noqa: SLF001
        assert filename.startswith("unknown")


class TestDownloadRunnerBuildProxies:
    """Tests for _build_proxies helper."""

    def test_proxy_from_arg(self):
        """Proxy from constructor argument is used."""
        runner = DownloadRunner(papers=[], output_directory="/tmp", proxy="http://proxy:8080")
        proxies = runner._build_proxies()  # noqa: SLF001
        assert proxies == {"http": "http://proxy:8080", "https": "http://proxy:8080"}

    def test_no_proxy_returns_none(self, monkeypatch):
        """None is returned when no proxy is configured."""
        monkeypatch.delenv("FINDPAPERS_PROXY", raising=False)
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        assert runner._build_proxies() is None  # noqa: SLF001

    def test_proxy_from_env(self, monkeypatch):
        """Proxy is read from FINDPAPERS_PROXY env variable."""
        monkeypatch.setenv("FINDPAPERS_PROXY", "http://env-proxy:9090")
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        proxies = runner._build_proxies()  # noqa: SLF001
        assert proxies is not None
        assert proxies["http"] == "http://env-proxy:9090"


class TestDownloadRunnerResolvePdfUrl:
    """Tests for _resolve_pdf_url publisher patterns."""

    def _runner(self):
        return DownloadRunner(papers=[], output_directory="/tmp")

    def test_unknown_host_returns_none(self):
        """Unknown host returns None."""
        runner = self._runner()
        result = runner._resolve_pdf_url(  # noqa: SLF001
            "https://unknown.host/article/123", _make_paper()
        )
        assert result is None

    def test_springer_url_resolved(self):
        """Springer URL is correctly resolved to PDF."""
        runner = self._runner()
        url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"
        result = runner._resolve_pdf_url(url, _make_paper())  # noqa: SLF001
        assert result is not None
        assert result.endswith(".pdf")
        assert "/content/pdf/" in result

    def test_ieee_url_with_document_path(self):
        """IEEE document URL is resolved using path."""
        runner = self._runner()
        url = "https://ieeexplore.ieee.org/document/12345"
        result = runner._resolve_pdf_url(url, _make_paper())  # noqa: SLF001
        assert result is not None
        assert "12345" in result

    def test_frontiersin_url_resolved(self):
        """Frontiers in article URL resolved to PDF."""
        runner = self._runner()
        url = "https://www.frontiersin.org/articles/10.3389/fnins.2020.12345/full"
        result = runner._resolve_pdf_url(url, _make_paper())  # noqa: SLF001
        assert result is not None
        assert result.endswith("/pdf")


class TestDownloadRunnerRun:
    """Tests for the run() method."""

    def test_run_with_empty_list(self, tmp_path):
        """run() with empty paper list completes successfully."""
        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        runner.run()
        metrics = runner.get_metrics()
        assert metrics["total_papers"] == 0
        assert metrics["downloaded_papers"] == 0

    def test_metrics_populated_after_run(self, tmp_path):
        """Metrics contain expected keys after run()."""
        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(False, [])):
            runner.run()
        metrics = runner.get_metrics()
        assert "total_papers" in metrics
        assert "downloaded_papers" in metrics
        assert "runtime_in_seconds" in metrics

    def test_creates_output_directory(self, tmp_path):
        """run() creates the output directory when it does not exist."""
        out_dir = str(tmp_path / "nested" / "output")
        runner = DownloadRunner(papers=[], output_directory=out_dir)
        runner.run()
        assert os.path.isdir(out_dir)

    def test_download_success_increments_count(self, tmp_path):
        """Successful download increments downloaded_papers metric."""
        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://url"])):
            runner.run()
        assert runner.get_metrics()["downloaded_papers"] == 1

    def test_download_failure_logged(self, tmp_path):
        """Failed download leaves downloaded_papers at 0."""
        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(False, ["http://url"])):
            runner.run()
        assert runner.get_metrics()["downloaded_papers"] == 0
        # Error log must exist
        error_log = os.path.join(str(tmp_path), "download_errors.txt")
        assert os.path.exists(error_log)


class TestDownloadRunnerVerbose:
    """Tests for the verbose=True logging path."""

    def test_verbose_run_does_not_raise(self, tmp_path):
        """run(verbose=True) completes without raising."""

        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        # Should not raise.
        runner.run(verbose=True)
        assert runner.get_metrics()["total_papers"] == 0

    def test_verbose_true_emits_configuration_header(self, tmp_path, caplog):
        """verbose=True logs the DownloadRunner configuration header."""
        import logging

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://url"])):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)
        assert "DownloadRunner Configuration" in " ".join(caplog.messages)

    def test_verbose_true_emits_download_summary(self, tmp_path, caplog):
        """verbose=True logs the download summary after execution."""
        import logging

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://url"])):
            with caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Download Summary" in messages
        assert "Runtime" in messages

    def test_verbose_true_logs_download_error(self, tmp_path, caplog):
        """verbose=True logs a WARNING when a paper download fails."""
        import logging

        paper = _make_paper(title="Failing Paper")
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", side_effect=RuntimeError("network error")):
            with caplog.at_level(logging.WARNING, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)
        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Failing Paper" in str(w) for w in warnings)

    def test_verbose_false_emits_no_configuration_log(self, tmp_path, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        with caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"):
            runner.run(verbose=False)
        assert "DownloadRunner Configuration" not in " ".join(caplog.messages)

    def test_verbose_true_suppresses_third_party_loggers(self, tmp_path):
        """verbose=True sets noisy third-party loggers to WARNING to avoid credential leaks."""
        import logging

        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        runner.run(verbose=True)
        for lib in ("urllib3", "requests", "httpx", "charset_normalizer"):
            assert logging.getLogger(lib).level == logging.WARNING

    def test_verbose_true_masks_proxy_credentials(self, tmp_path, caplog):
        """verbose=True does not log proxy credentials in plain text."""
        import logging

        runner = DownloadRunner(
            papers=[],
            output_directory=str(tmp_path),
            proxy="http://user:secret@proxy.example.com:8080",
        )
        with caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "secret" not in messages
        assert "user" not in messages
        assert "proxy.example.com" in messages

    def test_request_and_response_logged_at_debug(self, tmp_path, caplog):
        """_request() logs GET url and response details at DEBUG level."""
        import logging
        from unittest.mock import MagicMock

        paper = _make_paper(title="Debug Log Paper")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch("findpapers.runners.download_runner.requests.get", return_value=mock_resp):
            with caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)

        debug_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "GET" in debug_messages
        assert "200" in debug_messages

    def test_response_not_logged_when_connection_fails(self, tmp_path, caplog):
        """No response log is emitted when requests.get raises (no connection established)."""
        import logging

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch(
            "findpapers.runners.download_runner.requests.get",
            side_effect=ConnectionError("refused"),
        ):
            with caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)

        debug_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        # GET is logged before the request attempt; response must NOT appear
        assert "GET" in debug_messages
        assert "<-" not in debug_messages

    def test_browser_headers_sent_in_request(self, tmp_path):
        """requests.get is called with browser-like headers to avoid bot detection."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"
        mock_resp.ok = True

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch(
            "findpapers.runners.download_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner.run()

        assert mock_get.called
        _, kwargs = mock_get.call_args
        headers = kwargs.get("headers", {})
        assert "User-Agent" in headers
        assert "python-requests" not in headers["User-Agent"].lower()
        assert "Mozilla" in headers["User-Agent"]

    def test_418_response_emits_warning(self, tmp_path, caplog):
        """A 418 response from bot-detection logs a WARNING with a clear message."""
        import logging
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 418
        mock_resp.reason = "I'm a Teapot"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.content = b"<html>blocked</html>"
        mock_resp.url = "http://example.com/paper"
        mock_resp.ok = False

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch("findpapers.runners.download_runner.requests.get", return_value=mock_resp):
            with caplog.at_level(logging.WARNING, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)

        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("418" in str(w) or "bot" in str(w).lower() for w in warnings)


class TestDownloadRunnerSslVerify:
    """Tests for the ssl_verify parameter."""

    def test_ssl_verify_defaults_to_true(self):
        """ssl_verify defaults to True when not specified."""
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        assert runner._ssl_verify is True  # noqa: SLF001

    def test_ssl_verify_stored_when_false(self):
        """ssl_verify=False is stored on the runner."""
        runner = DownloadRunner(papers=[], output_directory="/tmp", ssl_verify=False)
        assert runner._ssl_verify is False  # noqa: SLF001

    def test_ssl_verify_passed_to_requests_get(self, tmp_path):
        """ssl_verify value is forwarded to requests.get as verify=."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(
            papers=[_make_paper()],
            output_directory=str(tmp_path),
            ssl_verify=False,
        )
        with patch(
            "findpapers.runners.download_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner.run()

        assert mock_get.called
        _, kwargs = mock_get.call_args
        assert kwargs.get("verify") is False

    def test_ssl_verify_true_passed_to_requests_get(self, tmp_path):
        """ssl_verify=True (default) forwards verify=True to requests.get."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(
            papers=[_make_paper()],
            output_directory=str(tmp_path),
        )
        with patch(
            "findpapers.runners.download_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner.run()

        assert mock_get.called
        _, kwargs = mock_get.call_args
        assert kwargs.get("verify") is True

    def test_ssl_verify_logged_in_verbose_mode(self, tmp_path, caplog):
        """verbose=True includes ssl_verify value in the configuration log."""
        import logging

        runner = DownloadRunner(
            papers=[],
            output_directory=str(tmp_path),
            ssl_verify=False,
        )
        with caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "SSL verify" in messages
        assert "False" in messages

    def test_request_exception_logged_at_debug(self, tmp_path, caplog):
        """When requests.get raises, the exception is logged at DEBUG level."""
        import logging

        runner = DownloadRunner(papers=[_make_paper()], output_directory=str(tmp_path))
        with patch(
            "findpapers.runners.download_runner.requests.get",
            side_effect=ConnectionError("SSL handshake failed"),
        ):
            with caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"):
                runner.run(verbose=True)

        debug_messages = [r for r in caplog.records if r.levelno == logging.DEBUG]
        # At least one record should carry exc_info about the failure
        assert any(r.exc_info is not None for r in debug_messages)


class TestDownloadRunnerMaskProxyCredentials:
    """Tests for the _mask_proxy_credentials static method."""

    def test_none_returns_none_string(self):
        """None proxy returns the string 'none'."""
        assert DownloadRunner._mask_proxy_credentials(None) == "none"  # noqa: SLF001

    def test_proxy_without_credentials_returned_as_is(self):
        """Proxy URL without credentials is returned unchanged."""
        url = "http://proxy.example.com:8080"
        assert DownloadRunner._mask_proxy_credentials(url) == url  # noqa: SLF001

    def test_credentials_are_masked(self):
        """User and password in proxy URL are replaced with ***."""
        url = "http://user:secret@proxy.example.com:8080"
        masked = DownloadRunner._mask_proxy_credentials(url)  # noqa: SLF001
        assert "secret" not in masked
        assert "user" not in masked
        assert "proxy.example.com" in masked
        assert "8080" in masked
        assert "***:***@" in masked

    def test_only_username_masked(self):
        """A URL with only a username (no password) is also masked."""
        url = "http://user@proxy.example.com:3128"
        masked = DownloadRunner._mask_proxy_credentials(url)  # noqa: SLF001
        assert "user" not in masked
        assert "***:***@" in masked


class TestDownloadRunnerUrlPriority:
    """Tests that pdf_url is tried before other URLs."""

    @staticmethod
    def _make_pdf_response():
        """Return a mock response that looks like a PDF."""
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.headers = {"content-type": "application/pdf"}
        resp.content = b"%PDF-1.4 fake"
        resp.url = "http://example.com/paper.pdf"
        resp.ok = True
        return resp

    def test_pdf_url_tried_before_url(self, tmp_path):
        """When both pdf_url and url are set, pdf_url is tried first."""
        paper = Paper(
            title="Priority Test",
            abstract="Abstract.",
            authors=["Author"],
            publication=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/landing",
            pdf_url="http://example.com/paper.pdf",
        )
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        call_order: list[str] = []

        def _fake_request(url: str, **kwargs):
            call_order.append(url)
            return self._make_pdf_response()

        with patch.object(runner, "_request", side_effect=_fake_request):
            runner.run()

        assert (
            call_order[0] == "http://example.com/paper.pdf"
        ), "pdf_url must be the first URL tried"
        assert runner.get_metrics()["downloaded_papers"] == 1

    def test_falls_back_to_url_when_pdf_url_fails(self, tmp_path):
        """When pdf_url request fails, url is tried next."""
        paper = Paper(
            title="Fallback Test",
            abstract="Abstract.",
            authors=["Author"],
            publication=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/landing",
            pdf_url="http://example.com/broken.pdf",
        )
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        call_order: list[str] = []

        def _fake_request(url: str, **kwargs):
            call_order.append(url)
            if "broken" in url:
                return None  # simulate failure
            return self._make_pdf_response()

        with patch.object(runner, "_request", side_effect=_fake_request):
            runner.run()

        assert call_order[0] == "http://example.com/broken.pdf"
        assert "http://example.com/landing" in call_order
        assert runner.get_metrics()["downloaded_papers"] == 1

    def test_only_url_when_no_pdf_url(self, tmp_path):
        """When pdf_url is not set, url is used directly."""
        paper = Paper(
            title="No PDF URL",
            abstract="Abstract.",
            authors=["Author"],
            publication=None,
            publication_date=date(2023, 1, 1),
            url="http://example.com/landing",
            pdf_url=None,
        )
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        call_order: list[str] = []

        def _fake_request(url: str, **kwargs):
            call_order.append(url)
            return self._make_pdf_response()

        with patch.object(runner, "_request", side_effect=_fake_request):
            runner.run()

        assert call_order[0] == "http://example.com/landing"
        assert runner.get_metrics()["downloaded_papers"] == 1

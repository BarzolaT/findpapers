"""Unit tests for DownloadRunner."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.runners.download_runner import DownloadRunner


class TestDownloadRunnerInit:
    """Tests for DownloadRunner initialisation."""

    def test_init_stores_config(self, make_paper):
        """Constructor stores configuration without executing."""
        papers = [make_paper()]
        runner = DownloadRunner(papers=papers, output_directory="/tmp/out")
        assert runner._output_directory == "/tmp/out"


class TestDownloadRunnerBuildFilename:
    """Tests for _build_filename helper."""

    def test_filename_includes_year_and_title(self, make_paper):
        """Filename starts with year and contains sanitised title."""
        paper = make_paper(title="My Test Paper")
        paper.publication_date = date(2023, 5, 1)
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)
        assert filename.startswith("2023")
        assert filename.endswith(".pdf")

    def test_filename_sanitises_spaces(self, make_paper):
        """Spaces in title are replaced with underscores."""
        paper = make_paper(title="Hello World")
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)
        assert " " not in filename

    def test_filename_unknown_year_when_no_date(self, make_paper):
        """Papers without publication_date use 'unknown' as year."""
        paper = make_paper()
        paper.publication_date = None
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        filename = runner._build_filename(paper)
        assert filename.startswith("unknown")


class TestDownloadRunnerBuildProxies:
    """Tests for _build_proxies helper."""

    def test_proxy_from_arg(self):
        """Proxy from constructor argument is used."""
        runner = DownloadRunner(papers=[], output_directory="/tmp", proxy="http://proxy:8080")
        proxies = runner._build_proxies()
        assert proxies == {"http": "http://proxy:8080", "https": "http://proxy:8080"}

    def test_no_proxy_returns_none(self, monkeypatch):
        """None is returned when no proxy is configured."""
        monkeypatch.delenv("FINDPAPERS_PROXY", raising=False)
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        assert runner._build_proxies() is None

    def test_proxy_from_env(self, monkeypatch):
        """Proxy is read from FINDPAPERS_PROXY env variable."""
        monkeypatch.setenv("FINDPAPERS_PROXY", "http://env-proxy:9090")
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        proxies = runner._build_proxies()
        assert proxies is not None
        assert proxies["http"] == "http://env-proxy:9090"


class TestDownloadRunnerResolvePdfUrl:
    """Tests for _resolve_pdf_url publisher patterns."""

    def _runner(self):
        return DownloadRunner(papers=[], output_directory="/tmp")

    def test_unknown_host_returns_none(self, make_paper):
        """Unknown host returns None."""
        runner = self._runner()
        result = runner._resolve_pdf_url("https://unknown.host/article/123", make_paper())
        assert result is None

    def test_springer_url_resolved(self, make_paper):
        """Springer URL is correctly resolved to PDF."""
        runner = self._runner()
        url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"
        result = runner._resolve_pdf_url(url, make_paper())
        assert result is not None
        assert result.endswith(".pdf")
        assert "/content/pdf/" in result

    def test_ieee_url_with_document_path(self, make_paper):
        """IEEE document URL is resolved using path."""
        runner = self._runner()
        url = "https://ieeexplore.ieee.org/document/12345"
        result = runner._resolve_pdf_url(url, make_paper())
        assert result is not None
        assert "12345" in result

    def test_frontiersin_url_resolved(self, make_paper):
        """Frontiers in article URL resolved to PDF."""
        runner = self._runner()
        url = "https://www.frontiersin.org/articles/10.3389/fnins.2020.12345/full"
        result = runner._resolve_pdf_url(url, make_paper())
        assert result is not None
        assert result.endswith("/pdf")


class TestDownloadRunnerRun:
    """Tests for the run() method."""

    def test_run_with_empty_list(self, tmp_path):
        """run() with empty paper list completes successfully."""
        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        metrics = runner.run()
        assert metrics["total_papers"] == 0
        assert metrics["downloaded_papers"] == 0

    def test_metrics_populated_after_run(self, make_paper, tmp_path):
        """Metrics contain expected keys after run()."""
        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(False, [])):
            metrics = runner.run()
        assert "total_papers" in metrics
        assert "downloaded_papers" in metrics
        assert "runtime_in_seconds" in metrics

    def test_creates_output_directory(self, tmp_path):
        """run() creates the output directory when it does not exist."""
        out_dir = str(tmp_path / "nested" / "output")
        runner = DownloadRunner(papers=[], output_directory=out_dir)
        runner.run()
        assert os.path.isdir(out_dir)

    def test_download_success_increments_count(self, make_paper, tmp_path):
        """Successful download increments downloaded_papers metric."""
        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://url"])):
            metrics = runner.run()
        assert metrics["downloaded_papers"] == 1

    def test_download_failure_logged(self, make_paper, tmp_path):
        """Failed download leaves downloaded_papers at 0."""
        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(False, ["http://url"])):
            metrics = runner.run()
        assert metrics["downloaded_papers"] == 0
        # Log file must exist with a [FAILED] entry
        log_file = os.path.join(str(tmp_path), "download_log.txt")
        assert os.path.exists(log_file)
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "[FAILED]" in content

    def test_download_success_logged(self, make_paper, tmp_path):
        """Successful download is logged with [OK] prefix."""
        paper = make_paper(title="Good Paper")
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://ok-url"])):
            runner.run()
        log_file = os.path.join(str(tmp_path), "download_log.txt")
        assert os.path.exists(log_file)
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "[OK] Good Paper" in content
        assert "http://ok-url" in content

    def test_log_contains_both_success_and_failure(self, make_paper, tmp_path):
        """Download log contains both [OK] and [FAILED] entries."""
        papers = [make_paper(title="Success Paper"), make_paper(title="Failure Paper")]
        runner = DownloadRunner(papers=papers, output_directory=str(tmp_path))
        results = iter([(True, ["http://ok"]), (False, ["http://fail"])])
        with patch.object(runner, "_download_paper", side_effect=lambda *a, **kw: next(results)):
            runner.run()
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "[OK] Success Paper" in content
        assert "[FAILED] Failure Paper" in content

    def test_log_urls_are_indented(self, make_paper, tmp_path):
        """URLs in the log are indented with '  -> ' prefix."""
        paper = make_paper(title="Indented URL Paper")
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch.object(runner, "_download_paper", return_value=(True, ["http://indented-url"])):
            runner.run()
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "  -> http://indented-url" in content

    def test_log_session_header_contains_separator(self, tmp_path):
        """Log header uses '=' separator lines."""
        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        runner.run()
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "=" * 80 in content
        assert "Download session started:" in content

    def test_log_failure_no_urls_uses_placeholder(self, make_paper, tmp_path):
        """Failure with no URLs logs a '(no URLs available)' placeholder."""
        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        # Raising an exception triggers the error path which calls _log_download_error([]).
        with patch.object(runner, "_download_paper", side_effect=RuntimeError("boom")):
            runner.run()
        content = (tmp_path / "download_log.txt").read_text(encoding="utf-8")
        assert "(no URLs available)" in content


class TestDownloadRunnerVerbose:
    """Tests for the verbose=True logging path."""

    def test_verbose_run_does_not_raise(self, tmp_path):
        """run(verbose=True) completes without raising."""

        runner = DownloadRunner(papers=[], output_directory=str(tmp_path))
        # Should not raise.
        metrics = runner.run(verbose=True)
        assert metrics["total_papers"] == 0

    def test_verbose_true_emits_configuration_header(self, make_paper, tmp_path, caplog):
        """verbose=True logs the DownloadRunner configuration header."""
        import logging

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with (
            patch.object(runner, "_download_paper", return_value=(True, ["http://url"])),
            caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)
        assert "DownloadRunner Configuration" in " ".join(caplog.messages)

    def test_verbose_true_emits_download_summary(self, make_paper, tmp_path, caplog):
        """verbose=True logs the download summary after execution."""
        import logging

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with (
            patch.object(runner, "_download_paper", return_value=(True, ["http://url"])),
            caplog.at_level(logging.INFO, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Download Summary" in messages
        assert "Runtime" in messages

    def test_verbose_true_logs_download_error(self, make_paper, tmp_path, caplog):
        """verbose=True logs a WARNING when a paper download fails."""
        import logging

        paper = make_paper(title="Failing Paper")
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with (
            patch.object(runner, "_download_paper", side_effect=RuntimeError("network error")),
            caplog.at_level(logging.WARNING, logger="findpapers.runners.download_runner"),
        ):
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

    def test_show_progress_false_disables_progress_bar(self, make_paper, tmp_path):
        """show_progress=False suppresses the tqdm progress bar."""
        papers = [make_paper()]
        runner = DownloadRunner(papers=papers, output_directory=str(tmp_path))
        with (
            patch.object(runner, "_download_paper", return_value=(True, [])),
            patch("findpapers.utils.parallel.make_progress_bar") as mock_pbar,
        ):
            runner.run(show_progress=False)
            # Verify that make_progress_bar was called with disable=True
            assert mock_pbar.called
            for call in mock_pbar.call_args_list:
                assert call.kwargs.get("disable") is True

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

    def test_request_and_response_logged_at_debug(self, make_paper, tmp_path, caplog):
        """_request() logs GET url and response details at DEBUG level."""
        import logging
        from unittest.mock import MagicMock

        paper = make_paper(title="Debug Log Paper")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with (
            patch("findpapers.runners.download_runner.requests.get", return_value=mock_resp),
            caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)

        debug_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "GET" in debug_messages
        assert "200" in debug_messages

    def test_response_not_logged_when_connection_fails(self, make_paper, tmp_path, caplog):
        """No response log is emitted when requests.get raises (no connection established)."""
        import logging

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with (
            patch(
                "findpapers.runners.download_runner.requests.get",
                side_effect=ConnectionError("refused"),
            ),
            caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)

        debug_messages = " ".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        # GET is logged before the request attempt; response must NOT appear
        assert "GET" in debug_messages
        assert "<-" not in debug_messages

    def test_browser_headers_sent_in_request(self, make_paper, tmp_path):
        """requests.get is called with browser-like headers to avoid bot detection."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"
        mock_resp.ok = True

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
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

    def test_418_response_emits_warning(self, make_paper, tmp_path, caplog):
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

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with (
            patch("findpapers.runners.download_runner.requests.get", return_value=mock_resp),
            caplog.at_level(logging.WARNING, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)

        warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("418" in str(w) or "bot" in str(w).lower() for w in warnings)


class TestDownloadRunnerSslVerify:
    """Tests for the ssl_verify parameter."""

    def test_ssl_verify_defaults_to_true(self):
        """ssl_verify defaults to True when not specified."""
        runner = DownloadRunner(papers=[], output_directory="/tmp")
        assert runner._ssl_verify is True

    def test_ssl_verify_stored_when_false(self):
        """ssl_verify=False is stored on the runner."""
        runner = DownloadRunner(papers=[], output_directory="/tmp", ssl_verify=False)
        assert runner._ssl_verify is False

    def test_ssl_verify_passed_to_requests_get(self, make_paper, tmp_path):
        """ssl_verify value is forwarded to requests.get as verify=."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(
            papers=[make_paper()],
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

    def test_ssl_verify_true_passed_to_requests_get(self, make_paper, tmp_path):
        """ssl_verify=True (default) forwards verify=True to requests.get."""
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.reason = "OK"
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.content = b"%PDF"
        mock_resp.url = "http://example.com/paper.pdf"

        runner = DownloadRunner(
            papers=[make_paper()],
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

    def test_request_exception_logged_at_debug(self, make_paper, tmp_path, caplog):
        """When requests.get raises, the exception is logged at DEBUG level."""
        import logging

        runner = DownloadRunner(papers=[make_paper()], output_directory=str(tmp_path))
        with (
            patch(
                "findpapers.runners.download_runner.requests.get",
                side_effect=ConnectionError("SSL handshake failed"),
            ),
            caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"),
        ):
            runner.run(verbose=True)

        debug_messages = [r for r in caplog.records if r.levelno == logging.DEBUG]
        # At least one record should carry exc_info about the failure
        assert any(r.exc_info is not None for r in debug_messages)


class TestDownloadRunnerMaskProxyCredentials:
    """Tests for the _mask_proxy_credentials static method."""

    def test_none_returns_none_string(self):
        """None proxy returns the string 'none'."""
        assert DownloadRunner._mask_proxy_credentials(None) == "none"

    def test_proxy_without_credentials_returned_as_is(self):
        """Proxy URL without credentials is returned unchanged."""
        url = "http://proxy.example.com:8080"
        assert DownloadRunner._mask_proxy_credentials(url) == url

    def test_credentials_are_masked(self):
        """User and password in proxy URL are replaced with ***."""
        url = "http://user:secret@proxy.example.com:8080"
        masked = DownloadRunner._mask_proxy_credentials(url)
        assert "secret" not in masked
        assert "user" not in masked
        assert "proxy.example.com" in masked
        assert "8080" in masked
        assert "***:***@" in masked

    def test_only_username_masked(self):
        """A URL with only a username (no password) is also masked."""
        url = "http://user@proxy.example.com:3128"
        masked = DownloadRunner._mask_proxy_credentials(url)
        assert "user" not in masked
        assert "***:***@" in masked

    def test_malformed_proxy_url_returned_as_is(self):
        """A badly-formed proxy URL that causes urlparse to fail is returned as-is."""

        def _raising_urlparse(url, *args, **kwargs):
            raise ValueError("boom")

        with patch("findpapers.runners.download_runner.urllib.parse.urlparse", _raising_urlparse):
            result = DownloadRunner._mask_proxy_credentials("not-a-url")
        assert result == "not-a-url"


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
            authors=[Author(name="Author")],
            source=None,
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
            metrics = runner.run()

        assert call_order[0] == "http://example.com/paper.pdf", (
            "pdf_url must be the first URL tried"
        )
        assert metrics["downloaded_papers"] == 1

    def test_falls_back_to_url_when_pdf_url_fails(self, tmp_path):
        """When pdf_url request fails, url is tried next."""
        paper = Paper(
            title="Fallback Test",
            abstract="Abstract.",
            authors=[Author(name="Author")],
            source=None,
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
            metrics = runner.run()

        assert call_order[0] == "http://example.com/broken.pdf"
        assert "http://example.com/landing" in call_order
        assert metrics["downloaded_papers"] == 1

    def test_only_url_when_no_pdf_url(self, tmp_path):
        """When pdf_url is not set, url is used directly."""
        paper = Paper(
            title="No PDF URL",
            abstract="Abstract.",
            authors=[Author(name="Author")],
            source=None,
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
            metrics = runner.run()

        assert call_order[0] == "http://example.com/landing"
        assert metrics["downloaded_papers"] == 1


class TestDownloadRunnerEdgeCases:
    """Tests for uncovered edge-case paths in _download_paper and _request."""

    @staticmethod
    def _make_response(status_code=200, content_type="application/pdf", content=b"%PDF"):
        """Build a minimal mock response."""
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.status_code = status_code
        resp.reason = "OK" if status_code == 200 else "Error"
        resp.headers = {"content-type": content_type}
        resp.content = content
        resp.url = "http://example.com/paper"
        resp.ok = status_code < 400
        return resp

    def test_existing_pdf_skipped(self, make_paper, tmp_path):
        """_download_paper returns True without HTTP call when PDF already exists."""
        paper = make_paper(title="Already There")
        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        # Pre-create the file that _build_filename would generate
        filename = runner._build_filename(paper)
        filepath = tmp_path / filename
        filepath.write_bytes(b"%PDF-existing")

        with patch("findpapers.runners.download_runner.requests.get") as mock_get:
            metrics = runner.run()

        # The file already existed so requests.get() should not be called.
        mock_get.assert_not_called()
        assert metrics["downloaded_papers"] == 1

    def test_doi_url_used_as_candidate(self, make_paper, tmp_path):
        """DOI-based URL is used when paper has a DOI but no pdf_url/url."""
        paper = make_paper(title="DOI Only")
        paper.pdf_url = None
        paper.url = None
        paper.doi = "10.1234/test"

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        resp = self._make_response()
        with patch("findpapers.runners.download_runner.requests.get", return_value=resp) as mg:
            runner.run()

        called_url = mg.call_args[0][0]
        assert "doi.org/10.1234/test" in called_url

    def test_html_response_resolves_to_pdf(self, make_paper, tmp_path):
        """HTML response triggers _resolve_pdf_url and follows the resolved URL."""
        paper = make_paper(title="HTML Redirect")
        paper.pdf_url = None
        paper.url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"
        paper.doi = None

        html_resp = self._make_response(content_type="text/html", content=b"<html>")
        html_resp.url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"
        pdf_resp = self._make_response(content_type="application/pdf", content=b"%PDF-data")

        call_count = {"n": 0}

        def _fake_get(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return html_resp
            return pdf_resp

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch("findpapers.runners.download_runner.requests.get", side_effect=_fake_get):
            metrics = runner.run()

        assert metrics["downloaded_papers"] == 1
        assert call_count["n"] == 2

    def test_non_ok_response_logged(self, make_paper, tmp_path, caplog):
        """Non-success status (non-418) logs at DEBUG level."""
        import logging

        paper = make_paper(title="Server Error")
        paper.pdf_url = "http://example.com/broken"
        paper.url = None
        paper.doi = None

        resp = self._make_response(status_code=500, content_type="text/html", content=b"error")
        resp.ok = False

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with (
            patch("findpapers.runners.download_runner.requests.get", return_value=resp),
            caplog.at_level(logging.DEBUG, logger="findpapers.runners.download_runner"),
        ):
            runner.run()

        debug_msgs = " ".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "500" in debug_msgs

    def test_download_exception_caught(self, make_paper, tmp_path):
        """Exception during _download_paper loop is caught; download returns False."""
        paper = make_paper(title="Exception Paper")
        paper.pdf_url = "http://example.com/paper.pdf"
        paper.url = None
        paper.doi = None

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))

        def _exploding_get(url, **kwargs):
            raise RuntimeError("unexpected boom")

        with patch("findpapers.runners.download_runner.requests.get", side_effect=_exploding_get):
            metrics = runner.run()

        assert metrics["downloaded_papers"] == 0

    def test_proxy_with_port_masked(self):
        """Proxy URL with user:pass and port masks credentials but keeps port."""
        masked = DownloadRunner._mask_proxy_credentials("http://myuser:mypass@proxy.local:9090")
        assert "myuser" not in masked
        assert "mypass" not in masked
        assert "9090" in masked
        assert "proxy.local" in masked

    def test_html_resolved_pdf_url_returns_none(self, make_paper, tmp_path):
        """When resolved PDF URL request returns None, download continues to next URL."""
        paper = make_paper(title="Resolved None")
        paper.pdf_url = None
        paper.url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"
        paper.doi = None

        html_resp = self._make_response(content_type="text/html", content=b"<html>")
        html_resp.url = "https://link.springer.com/article/10.1007/s00000-000-0000-0"

        call_count = {"n": 0}

        def _fake_get(url, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return html_resp
            # Resolved PDF URL request fails
            return None

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch.object(runner, "_request", side_effect=_fake_get):
            metrics = runner.run()

        assert metrics["downloaded_papers"] == 0
        assert call_count["n"] == 2

    def test_download_loop_exception_is_caught(self, make_paper, tmp_path):
        """Exception raised inside download loop is caught, paper not downloaded."""
        paper = make_paper(title="Loop Exception")
        paper.pdf_url = "http://example.com/paper.pdf"
        paper.url = None
        paper.doi = None

        resp = self._make_response(content_type="application/pdf")
        # Make response.content raise to trigger the broad except
        type(resp).content = property(lambda self: (_ for _ in ()).throw(OSError("disk full")))

        runner = DownloadRunner(papers=[paper], output_directory=str(tmp_path))
        with patch("findpapers.runners.download_runner.requests.get", return_value=resp):
            metrics = runner.run()

        assert metrics["downloaded_papers"] == 0

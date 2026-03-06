"""Unit tests for EnrichmentRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from findpapers.runners.enrichment_runner import EnrichmentRunner

# Minimal metadata dict that makes _fetch_url_metadata look successful (HTML with a title).
_FAKE_METADATA: dict = {"citation_title": "Test Paper"}


class TestEnrichmentRunnerInit:
    """Tests for EnrichmentRunner initialisation."""

    def test_init_stores_papers(self, make_paper):
        """Constructor stores a copy of the paper list."""
        papers = [make_paper()]
        runner = EnrichmentRunner(papers=papers)
        assert runner._results is not papers  # noqa: SLF001
        assert len(runner._results) == 1  # noqa: SLF001


class TestEnrichmentRunnerRun:
    """Tests for the run() method."""

    def test_run_with_empty_papers(self):
        """run() on empty list completes without errors."""
        runner = EnrichmentRunner(papers=[])
        metrics = runner.run()
        assert metrics["total_papers"] == 0
        assert metrics["enriched_papers"] == 0

    def test_metrics_populated_after_run(self, make_paper):
        """Metrics contain all expected keys after run()."""
        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
        ):
            metrics = runner.run()
        assert "total_papers" in metrics
        assert "enriched_papers" in metrics
        assert "doi_enriched_papers" in metrics
        assert "fetch_error_papers" in metrics
        assert "no_metadata_papers" in metrics
        assert "no_change_papers" in metrics
        assert "no_urls_papers" in metrics
        assert "runtime_in_seconds" in metrics

    def test_enriched_count_incremented_on_success(self, make_paper):
        """enriched_papers increments only when new data is actually merged.

        The base paper is missing a DOI; the mock enriched paper supplies one,
        so the merge changes the snapshot and the counter must increment.
        """
        base = make_paper()
        base.doi = None  # ensure the field is absent before enrichment
        enriched_paper = make_paper(title="Enriched")
        enriched_paper.doi = "10.1234/test"
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=enriched_paper,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[base])
            metrics = runner.run()
        assert metrics["enriched_papers"] == 1

    def test_enriched_count_not_incremented_when_no_change(self, make_paper):
        """enriched_papers stays 0 when the merge adds nothing new.

        The base paper already has all the data the scraped paper can offer,
        so the snapshot is unchanged and the counter must not increment.
        """
        same_paper = make_paper()
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=same_paper,  # identical data — no improvement
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[make_paper()])
            metrics = runner.run()
        assert metrics["enriched_papers"] == 0

    def test_skips_papers_without_urls(self, make_paper):
        """Papers without URLs (and no DOI) return 'no_urls' without fetching."""
        paper = make_paper(url=None)
        paper.doi = None  # ensure no DOI fallback URL either
        runner = EnrichmentRunner(papers=[paper])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata"
            ) as mock_fetch,
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work") as mock_crossref,
        ):
            metrics = runner.run()
        mock_fetch.assert_not_called()
        mock_crossref.assert_not_called()
        assert metrics["enriched_papers"] == 0
        assert metrics["no_urls_papers"] == 1

    def test_run_twice_resets(self, make_paper):
        """run() can be called multiple times; metrics are fresh each time."""
        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
        ):
            runner.run()
            metrics = runner.run()
        assert metrics["enriched_papers"] == 0

    def test_parallel_run(self, make_paper):
        """Parallel run completes and returns metrics."""
        papers = [make_paper(f"Paper {i}") for i in range(5)]
        runner = EnrichmentRunner(papers=papers, num_workers=3)
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
        ):
            metrics = runner.run()
        assert metrics["total_papers"] == 5

    def test_fetch_error_counted_when_url_raises(self, make_paper):
        """fetch_error_papers counts papers whose URL fetch raised an HTTP/network error."""
        paper = make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch(
            "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
            side_effect=RuntimeError("network error"),
        ):
            metrics = runner.run()
        assert metrics["fetch_error_papers"] == 1
        assert metrics["enriched_papers"] == 0

    def test_no_metadata_counted_when_fetch_returns_none(self, make_paper):
        """no_metadata_papers counts papers whose URL returned non-HTML content."""
        paper = make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch(
            "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
            return_value=None,
        ):
            metrics = runner.run()
        assert metrics["no_metadata_papers"] == 1
        assert metrics["enriched_papers"] == 0

    def test_no_change_counted_when_merge_changes_nothing(self, make_paper):
        """no_change_papers counts papers where HTML was fetched but added no new data."""
        same_paper = make_paper()
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=same_paper,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[make_paper()])
            metrics = runner.run()
        assert metrics["no_change_papers"] == 1
        assert metrics["enriched_papers"] == 0

    def test_doi_url_added_as_candidate(self, make_paper):
        """When the paper has a DOI, https://doi.org/{doi} is tried as a candidate URL."""
        paper = make_paper()
        paper.doi = "10.1234/test"
        fetched_urls: list[str] = []

        def _record_fetch(url: str, timeout: object = None) -> None:
            fetched_urls.append(url)
            return None  # simulate non-HTML / no-metadata response

        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                side_effect=_record_fetch,
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()
        assert "https://doi.org/10.1234/test" in fetched_urls


class TestEnrichmentRunnerVerbose:
    """Tests for the verbose=True logging path."""

    def test_verbose_run_does_not_raise(self):
        """run(verbose=True) completes without raising."""
        runner = EnrichmentRunner(papers=[])
        metrics = runner.run(verbose=True)
        assert metrics["total_papers"] == 0

    def test_verbose_true_emits_configuration_header(self, make_paper, caplog):
        """verbose=True logs the EnrichmentRunner configuration header."""
        import logging

        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
            caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"),
        ):
            runner.run(verbose=True)
        assert "EnrichmentRunner Configuration" in " ".join(caplog.messages)

    def test_verbose_true_emits_enrichment_summary(self, make_paper, caplog):
        """verbose=True logs the enrichment summary after execution."""
        import logging

        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
            caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"),
        ):
            runner.run(verbose=True)
        messages = " ".join(caplog.messages)
        assert "Enrichment Summary" in messages
        assert "Runtime" in messages

    def test_verbose_true_tracks_fetch_errors(self, make_paper):
        """Fetch errors are counted in fetch_error_papers when URLs raise."""
        paper = make_paper()
        paper.doi = None  # no DOI so CrossRef is skipped
        runner = EnrichmentRunner(papers=[paper])
        with patch(
            "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
            side_effect=RuntimeError("network error"),
        ):
            metrics = runner.run(verbose=True)
        assert metrics["fetch_error_papers"] == 1

    def test_verbose_false_emits_no_configuration_log(self, make_paper, caplog):
        """verbose=False (default) does not log the configuration header."""
        import logging

        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
            caplog.at_level(logging.INFO, logger="findpapers.runners.enrichment_runner"),
        ):
            runner.run(verbose=False)
        assert "EnrichmentRunner Configuration" not in " ".join(caplog.messages)

    def test_show_progress_false_disables_progress_bar(self, make_paper):
        """show_progress=False suppresses the tqdm progress bar."""
        runner = EnrichmentRunner(papers=[make_paper()])
        with (
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
            patch("findpapers.connectors.crossref.CrossRefConnector.fetch_work", return_value=None),
            patch("findpapers.utils.parallel.make_progress_bar") as mock_pbar,
        ):
            runner.run(show_progress=False)
            assert mock_pbar.called
            for call in mock_pbar.call_args_list:
                assert call.kwargs.get("disable") is True

    def test_verbose_true_suppresses_third_party_loggers(self):
        """verbose=True sets noisy third-party loggers to WARNING to avoid credential leaks."""
        import logging

        runner = EnrichmentRunner(papers=[])
        runner.run(verbose=True)
        for lib in ("urllib3", "requests", "httpx", "charset_normalizer"):
            assert logging.getLogger(lib).level == logging.WARNING


class TestEnrichmentRunnerCrossRef:
    """Tests for DOI-based enrichment via the CrossRef API."""

    def test_crossref_enriches_paper_with_doi(self, make_paper):
        """Papers with a DOI attempt CrossRef API enrichment."""
        paper = make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None  # missing data that CrossRef will fill

        crossref_paper = make_paper(title="CrossRef Paper")
        crossref_paper.citations = 42

        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value={"title": ["CrossRef Paper"]},
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            metrics = runner.run()

        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert paper.citations == 42

    def test_crossref_not_called_without_doi(self, make_paper):
        """Papers without DOI skip CrossRef entirely."""
        paper = make_paper()
        paper.doi = None

        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
            ) as mock_crossref,
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            runner.run()

        mock_crossref.assert_not_called()

    def test_crossref_error_falls_back_to_url_scraping(self, make_paper):
        """CrossRef error does not prevent URL-based enrichment."""
        paper = make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None

        enriched_paper = make_paper(title="Scraped")
        enriched_paper.citations = 10

        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                side_effect=RuntimeError("CrossRef timeout"),
            ),
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=enriched_paper,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            metrics = runner.run()

        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 0
        assert paper.citations == 10

    def test_crossref_and_scraping_both_contribute(self, make_paper):
        """Both CrossRef and URL scraping can contribute data to the same paper."""
        paper = make_paper()
        paper.doi = "10.1234/test"
        paper.citations = None
        paper.pdf_url = None

        # CrossRef provides citations but not pdf_url
        crossref_paper = make_paper(title="CrossRef")
        crossref_paper.citations = 100
        crossref_paper.pdf_url = None

        # URL scraping provides pdf_url
        scraped_paper = make_paper(title="Scraped")
        scraped_paper.pdf_url = "https://example.com/paper.pdf"
        scraped_paper.citations = None

        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value={"title": ["CrossRef"]},
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=_FAKE_METADATA,
            ),
            patch(
                "findpapers.runners.enrichment_runner.build_paper_from_metadata",
                return_value=scraped_paper,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            metrics = runner.run()

        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert paper.citations == 100
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_doi_only_paper_no_urls_enriches_via_crossref(self, make_paper):
        """Paper with DOI but no URL can still be enriched via CrossRef."""
        paper = make_paper(url=None)
        paper.doi = "10.1234/test"
        paper.citations = None

        crossref_paper = make_paper(title="CrossRef Only")
        crossref_paper.citations = 55

        with (
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.fetch_work",
                return_value={"title": ["CrossRef Only"]},
            ),
            patch(
                "findpapers.connectors.crossref.CrossRefConnector.build_paper",
                return_value=crossref_paper,
            ),
            patch(
                "findpapers.runners.enrichment_runner.EnrichmentRunner._fetch_url_metadata",
                return_value=None,
            ),
        ):
            runner = EnrichmentRunner(papers=[paper])
            metrics = runner.run()

        assert metrics["enriched_papers"] == 1
        assert metrics["doi_enriched_papers"] == 1
        assert metrics["no_urls_papers"] == 0


class TestFetchUrlMetadata:
    """Tests for the _fetch_url_metadata HTTP boundary method."""

    def test_returns_none_for_non_html_content_type(self, make_paper) -> None:
        """_fetch_url_metadata returns None when content-type is not text/html."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.text = ""
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()])
        with patch("findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp):
            result = runner._fetch_url_metadata("https://example.com/paper.pdf")  # noqa: SLF001
        assert result is None

    def test_returns_dict_for_html_content_type(self, make_paper) -> None:
        """_fetch_url_metadata returns a metadata dict for HTML responses."""
        html = '<html><head><meta name="citation_title" content="Test"></head></html>'
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.text = html
        mock_resp.content = html.encode()
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()])
        with patch("findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp):
            result = runner._fetch_url_metadata("https://example.com/paper")  # noqa: SLF001
        assert isinstance(result, dict)
        assert result.get("citation_title") == "Test"

    def test_proxy_forwarded_to_requests(self, make_paper) -> None:
        """When proxy is configured, requests.get receives the proxies dict."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><head></head></html>"
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()], proxy="http://proxy:8080")
        with patch(
            "findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner._fetch_url_metadata("https://example.com")  # noqa: SLF001

        _, kwargs = mock_get.call_args
        assert kwargs["proxies"] == {"http": "http://proxy:8080", "https": "http://proxy:8080"}

    def test_ssl_verify_forwarded_to_requests(self, make_paper) -> None:
        """When ssl_verify=False, requests.get receives verify=False."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><head></head></html>"
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()], ssl_verify=False)
        with patch(
            "findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner._fetch_url_metadata("https://example.com")  # noqa: SLF001

        _, kwargs = mock_get.call_args
        assert kwargs["verify"] is False

    def test_ssl_verify_defaults_to_true(self, make_paper) -> None:
        """By default, requests.get receives verify=True."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><head></head></html>"
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()])
        with patch(
            "findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner._fetch_url_metadata("https://example.com")  # noqa: SLF001

        _, kwargs = mock_get.call_args
        assert kwargs["verify"] is True

    def test_no_proxy_sends_none(self, make_paper) -> None:
        """When no proxy is configured, proxies=None is passed."""
        mock_resp = MagicMock()
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.text = "<html><head></head></html>"
        mock_resp.content = b""
        mock_resp.raise_for_status = MagicMock()

        runner = EnrichmentRunner(papers=[make_paper()])
        with patch(
            "findpapers.runners.enrichment_runner.requests.get", return_value=mock_resp
        ) as mock_get:
            runner._fetch_url_metadata("https://example.com")  # noqa: SLF001

        _, kwargs = mock_get.call_args
        assert kwargs["proxies"] is None

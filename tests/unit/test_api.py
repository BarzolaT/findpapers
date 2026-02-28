"""Unit tests for the public convenience functions in findpapers.api."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from findpapers.api import download, enrich, search
from findpapers.core.author import Author
from findpapers.core.paper import Paper
from findpapers.core.search import Search
from findpapers.core.source import Source


def _make_paper(
    title: str = "Test Paper",
    doi: str | None = None,
    url: str = "http://example.com/paper",
) -> Paper:
    """Create a minimal Paper for testing."""
    return Paper(
        title=title,
        abstract="An abstract.",
        authors=[Author(name="Author One")],
        source=Source(title="Test Journal"),
        publication_date=date(2023, 1, 1),
        url=url,
        doi=doi,
    )


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------


class TestSearchConvenience:
    """Tests for the ``search()`` convenience function."""

    def test_search_delegates_to_runner(self):
        """search() creates a SearchRunner, calls run(), and returns the Search object."""
        fake_search = MagicMock(spec=Search)
        with patch("findpapers.api.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = fake_search
            mock_cls.return_value = mock_runner

            result = search(
                "ti[machine learning]",
                databases=["arxiv"],
                max_papers_per_database=10,
                num_workers=2,
                verbose=True,
            )

        mock_cls.assert_called_once_with(
            query="ti[machine learning]",
            databases=["arxiv"],
            max_papers_per_database=10,
            ieee_api_key=None,
            scopus_api_key=None,
            pubmed_api_key=None,
            openalex_api_key=None,
            openalex_email=None,
            semantic_scholar_api_key=None,
            num_workers=2,
        )
        mock_runner.run.assert_called_once_with(verbose=True)
        assert result is fake_search

    def test_search_passes_api_keys(self):
        """All API-key parameters are forwarded to SearchRunner."""
        with patch("findpapers.api.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock(spec=Search)
            mock_cls.return_value = mock_runner

            search(
                "[ml]",
                ieee_api_key="ieee",
                scopus_api_key="scopus",
                pubmed_api_key="pubmed",
                openalex_api_key="oalex",
                openalex_email="me@example.com",
                semantic_scholar_api_key="s2",
            )

        _, kwargs = mock_cls.call_args
        assert kwargs["ieee_api_key"] == "ieee"
        assert kwargs["scopus_api_key"] == "scopus"
        assert kwargs["pubmed_api_key"] == "pubmed"
        assert kwargs["openalex_api_key"] == "oalex"
        assert kwargs["openalex_email"] == "me@example.com"
        assert kwargs["semantic_scholar_api_key"] == "s2"

    def test_search_default_verbose_is_false(self):
        """verbose defaults to False when not specified."""
        with patch("findpapers.api.SearchRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.run.return_value = MagicMock(spec=Search)
            mock_cls.return_value = mock_runner

            search("[ml]")

        mock_runner.run.assert_called_once_with(verbose=False)


# ---------------------------------------------------------------------------
# download()
# ---------------------------------------------------------------------------


class TestDownloadConvenience:
    """Tests for the ``download()`` convenience function."""

    def test_download_delegates_to_runner(self):
        """download() creates a DownloadRunner, calls run(), and returns metrics."""
        fake_metrics = {"total_papers": 1, "downloaded_papers": 1, "runtime_in_seconds": 0.5}
        with patch("findpapers.api.DownloadRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.get_metrics.return_value = fake_metrics
            mock_cls.return_value = mock_runner

            papers = [_make_paper()]
            result = download(
                papers,
                "/tmp/pdfs",
                num_workers=3,
                timeout=15.0,
                proxy="http://proxy:8080",
                ssl_verify=False,
                verbose=True,
            )

        mock_cls.assert_called_once_with(
            papers=papers,
            output_directory="/tmp/pdfs",
            num_workers=3,
            timeout=15.0,
            proxy="http://proxy:8080",
            ssl_verify=False,
        )
        mock_runner.run.assert_called_once_with(verbose=True)
        mock_runner.get_metrics.assert_called_once()
        assert result == fake_metrics

    def test_download_default_parameters(self):
        """Default values are forwarded correctly."""
        with patch("findpapers.api.DownloadRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.get_metrics.return_value = {}
            mock_cls.return_value = mock_runner

            download([], "/tmp/out")

        _, kwargs = mock_cls.call_args
        assert kwargs["num_workers"] == 1
        assert kwargs["timeout"] == 10.0
        assert kwargs["proxy"] is None
        assert kwargs["ssl_verify"] is True


# ---------------------------------------------------------------------------
# enrich()
# ---------------------------------------------------------------------------


class TestEnrichConvenience:
    """Tests for the ``enrich()`` convenience function."""

    def test_enrich_delegates_to_runner(self):
        """enrich() creates an EnrichmentRunner, calls run(), and returns metrics."""
        fake_metrics = {"total_papers": 2, "enriched_papers": 1, "runtime_in_seconds": 1.0}
        with patch("findpapers.api.EnrichmentRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.get_metrics.return_value = fake_metrics
            mock_cls.return_value = mock_runner

            papers = [_make_paper(), _make_paper(title="Another Paper")]
            result = enrich(
                papers,
                num_workers=4,
                timeout=20.0,
                verbose=True,
            )

        mock_cls.assert_called_once_with(
            papers=papers,
            num_workers=4,
            timeout=20.0,
        )
        mock_runner.run.assert_called_once_with(verbose=True)
        mock_runner.get_metrics.assert_called_once()
        assert result == fake_metrics

    def test_enrich_default_parameters(self):
        """Default values are forwarded correctly."""
        with patch("findpapers.api.EnrichmentRunner") as mock_cls:
            mock_runner = MagicMock()
            mock_runner.get_metrics.return_value = {}
            mock_cls.return_value = mock_runner

            enrich([])

        _, kwargs = mock_cls.call_args
        assert kwargs["num_workers"] == 1
        assert kwargs["timeout"] == 10.0


# ---------------------------------------------------------------------------
# Top-level imports
# ---------------------------------------------------------------------------


class TestTopLevelImports:
    """Verify that convenience functions are accessible from findpapers namespace."""

    def test_search_importable(self):
        """findpapers.search is the convenience function."""
        import findpapers

        assert callable(findpapers.search)

    def test_download_importable(self):
        """findpapers.download is the convenience function."""
        import findpapers

        assert callable(findpapers.download)

    def test_enrich_importable(self):
        """findpapers.enrich is the convenience function."""
        import findpapers

        assert callable(findpapers.enrich)
